# -*- coding: utf-8 -*-
'''
Module for deploying DEB packages on wide scale
'''

import logging, pickle, copy
import logging.handlers
#import salt.log

import salt.utils
import salt.config
import salt.loader
import salt.modules.aptpkg
#from salt.modules import aptpkg
from debian import deb822

from salt.modules.debdeploy_restart import *
from salt.exceptions import (
    CommandExecutionError, MinionError, SaltInvocationError
)


def log_hack(msg):
    log_file = open("/var/log/debdeploy.log", "a")
    log_file.write(msg + "\n")
    log_file.close()

# Doesn't work, WTF?
log = logging.getLogger('debdeploy')

__opts__ = salt.config.minion_config('/etc/salt/minion')
grains = salt.loader.grains(__opts__)

def list_pkgs():
    '''
    This Salt function returns a dictionary of installed Debian packages and their 
    respective installed version (keyed by the package name).

    It is mostly used by other debdeploy Salt modules to determine whether packages
    were updated, installed or removed.
    '''

    cmd = 'dpkg-query --showformat=\'${Status} ${Package} ' \
          '${Version} ${Architecture}\n\' -W'
    pkgs = {}

    out = __salt__['cmd.run_stdout'](cmd, output_loglevel='debug')
    for line in out.splitlines():
        cols = line.split()
        try:
            linetype, status, name, version_num, arch = \
                [cols[x] for x in (0, 2, 3, 4, 5)]
        except ValueError:
            continue
        if __grains__.get('cpuarch', '') == 'x86_64':
            osarch = __grains__.get('osarch', '')
            if arch != 'all' and osarch == 'amd64' and osarch != arch:
                name += ':{0}'.format(arch)
        if len(cols):
            if ('install' in linetype or 'hold' in linetype) and \
                    'installed' in status:
                pkgs[name] = version_num

    return pkgs


def restart_service(programs):
    '''
    This Salt function restarts services based on the process name. It is 
    checked whether the process is running at all (the command might be
    applied to a set of hosts of which not all systems actually have the
    daemon running).

    The restart behaviour is based on heuristics:
    - Processes started through systemd are determined by control groups
    - Upstart jobs are required from "initctl list"
    - If a process was started neither through upstart nor systemd and
      /etc/init.d/processname exists, the sysvinit script is restarted

    In addition, special restart handlers can be started. Restart handlers
    can implement advanced restart actions, e.g. suspend-resume-restart
    KVM instances after a QEMU update. Restart handlers are either shipped
    by other Debian packages and created locally as executable scripts at
    /usr/lib/debdeploy/PACKAGE.restart. The restart scripts should return 
    "0" in case of a successful restart and "1" in case of an error. 
    Restart handlers are executed as "restarthandler.NAME".

    Returns a dictionary of integers indicating the restart success (keyed by processes/handlers):
    0 = Success
    1 = Failed to restart
    2 = Process wasn't running before
    3 = Could not find restart handler
    '''

    # Known exceptions which break the rule of the daemon process being different from the
    # base name of the sysvinit script. Only relevant for sysvinit, which fortunately is fading out
    servicemap = {}
    servicemap['ntpd'] = 'ntp'

    results = {}
    for program in programs:

        if program.startswith("restarthandler."):
            handler = os.path.join("/usr/lib/debdeploy/",  program.split(".")[1] + ".restart")
            if not os.path.exists(handler):
                results[program] = 3
            else:
                try:
                    if subprocess.call(handler) == 0:
                        results[program] = 0
                    else:
                        results[program] = 1
                except OSError:
                    results[program] = 1
            break


        try:
            pid = subprocess.check_output(["/bin/pidof", "-x", "-s", program])[:-1]
        except subprocess.CalledProcessError, e:
            if e.returncode == 1:
                results[program] = 2
                break

        service = "undefined"

        if os.path.exists('/bin/systemd'): # systemd
            cgroup = os.path.join("/proc", pid, "cgroup")
            if os.path.exists(cgroup):
                f = open(cgroup, "r")
                for i in f.readlines():
                    if i.startswith("1:name"):
                        service = i.split("/")[-1].strip()
                f.close()

        elif os.path.exists('/sbin/initctl'): # upstart
            jobs = subprocess.check_output(["/sbin/initctl", "list"])
            for x in jobs.splitlines():
                if x.endswith(str(pid)):
                    service = x.split()[0]

        # no systemd or upstart job is present, let's check sysvinit
        if service == "undefined":
            # try a heuristic for sysvinit, in many cases the name of the daemon equals the init script name
            # apply some mapping for known exceptions

            program_basename = os.path.basename(program)
            if servicemap.has_key(program_basename):
                service = servicemap[program_basename]

            if os.path.exists(os.path.join('/etc/init.d/', program_basename)):
                service = program_basename

        logging.info("Restarting " + service + " for " + program)
        if __salt__['service.restart'](service):
            results[program] = 0
        else:
            results[program] = 1

    return results


def install_pkgs(binary_packages, downgrade = False):
    '''
    This Salt module installs software updates via apt

    binary_packages: A list of Debian binary package names to update (list of dictionaries)
    downgrade: If enabled, version downgrades are allowed (required to rollbacks to earlier versions)
    '''
    try:
        pkg_params, pkg_type = __salt__['pkg_resource.parse_targets'](pkgs=binary_packages)

    except MinionError as exc:
        raise CommandExecutionError(exc)

    if pkg_params is None or len(pkg_params) == 0:
        return {}
    if pkg_type == 'repository':
        targets = []
        for param, version_num in pkg_params.iteritems():
            if version_num is None:
                targets.append(param)
            else:
                targets.append('{0}={1}'.format(param, version_num.lstrip('=')))
        cmd = ['apt-get', '-q', '-y']
        if downgrade:
            cmd.append('--force-yes')
        cmd = cmd + ['-o', 'DPkg::Options::=--force-confold']
        cmd = cmd + ['-o', 'DPkg::Options::=--force-confdef']
        cmd.append('install')
        cmd.extend(targets)

    return __salt__['cmd.run_all'](cmd, python_shell=False, output_loglevel='debug')

def deploy(source, update_type, versions, **kwargs):
    '''
    Updates all installed binary packages of the source package
    to the specified version.

    source      : Name of the source package
    update_type : tool | library and others, see doc/readme.txt
    versions    : A dictionary of distros and the version to be installed,
                  e.g. jessie : 1.0-1.
                  If the distro isn't used, no update is performed
    '''

    pending_restarts_pre = set()
    pending_restarts_post = set()

    installed_distro = grains['oscodename']
    if not versions.has_key(installed_distro):
        logging.info("Update doesn't apply to the installed distribution (" + installed_distro + ")")
        return {}

    # Detect all locally installed binary packages of a given source package
    # The only resource we can use for that is parsing the /var/lib/dpkg/status
    # file. The format is a bit erratic: The Source: line is only present for
    # binary packages not having the same name as the binary package
    installed_binary_packages = []
    for pkg in deb822.Packages.iter_paragraphs(file('/var/lib/dpkg/status')):
        if pkg.has_key('Source') and pkg['Source'] == source:
            installed_binary_packages.append({pkg['Package'] : versions[installed_distro]})
        elif pkg.has_key('Package') and pkg['Package'] == source:
            installed_binary_packages.append({pkg['Package'] : versions[installed_distro]})

    if len(installed_binary_packages) == 0:
        logging.info("No binary packages installed for source package " + source)
        return {}

    if update_type == "library":
        pending_restarts_pre = Checkrestart().get_programs_to_restart()
        logging.debug("Packages needing a restart prior to the update:" + str(pending_restarts_pre))

    old = list_pkgs()

    logging.info("Refreshing apt package database")
    __salt__['pkg.refresh_db']

    apt_call = install_pkgs(installed_binary_packages)

    new = list_pkgs()

    if update_type == "library":
        pending_restarts_post = Checkrestart().get_programs_to_restart()
        logging.debug("Packages needing a restart after to the update:" + str(pending_restarts_post))

    ok = set(old.keys())
    nk = set(new.keys())

    additions = []
    removals = []
    updated = []
    restarts = []

    if update_type == "library":
        restarts = list(pending_restarts_post.difference(pending_restarts_pre))

    for i in nk.difference(ok):
        additions.append[i]
    for i in ok.difference(nk):
        removals.append[i]
    intersect = ok.intersection(nk)
    modified = {x : (old[x], new[x]) for x in intersect if old[x] != new[x]}

    logging.info("Newly installed packages:" + str(additions))
    logging.info("Removed packages: "  + str(removals))
    logging.info("Modified packages: " + str(modified))
    logging.info("Packages needing a restart: " + str(restarts))

    r = {}
    r["additions"] = additions
    r["removals"] = removals
    r["updated"] = modified
    r["restart"] = restarts
    r["aptlog"] = str(apt_call['stdout'])
    r["apterrlog"] = str(apt_call['stderr'])
    r["aptreturn"] = apt_call['retcode']

    jobid = kwargs.get('__pub_jid')
    jobfile = open("/var/lib/debdeploy/" + jobid + ".job", "w")
    pickle.dump(r, jobfile)
    jobfile.close()

    return r


def rollback(jobid):
    '''
    Roll back a software update specified by a Salt job ID

    '''
    jobfile = open("/var/lib/debdeploy/" + jobid + ".job", "r")
    r = pickle.load(jobfile)

    old = list_pkgs()
    __salt__['pkg.refresh_db']

    aptstderr = ""
    aptstdout = ""
    aptreturn = 0

    if len(r['updated'].keys()) > 0:
        pkgdowngrade = []
        for i in r['updated']:
            a = {}
            a[i] = r['updated'][i][0]
            pkgdowngrade.append(a)
        apt_call = install_pkgs(pkgdowngrade, downgrade=True)
        aptstderr += apt_call['stderr']
        aptstdout += apt_call['stdout']
        aptreturn += apt_call['retcode']

    if len(r['removals']) > 0:
        install_pkgs(r['removals'])
        aptstderr += apt_call['stderr']
        aptstdout += apt_call['stdout']
        aptreturn += apt_call['retcode']

    if len(r['additions']) > 0:
        __salt__['pkg.remove'] (pkgs=r['additions'])
        # TODO, capture output

    if aptreturn > 100:
        aptreturn = 100

    new = list_pkgs()
    ok = set(old.keys())
    nk = set(new.keys())

    additions = []
    removals = []
    updated = []
    restarts = []

    for i in nk.difference(ok):
        additions.append[i]
    for i in ok.difference(nk):
        removals.append[i]
    intersect = ok.intersection(nk)
    modified = {x : (old[x], new[x]) for x in intersect if old[x] != new[x]}

    logging.info("Newly installed packages:" + str(additions))
    logging.info("Removed packages: "  + str(removals))
    logging.info(modified)

    r = {}
    r["additions"] = additions
    r["removals"] = removals
    r["updated"] = modified
    r["restart"] = restarts
    r["aptlog"] = aptstdout
    r["apterrlog"] = aptstderr
    r["aptreturn"] = aptreturn

    return r

# Local variables:
# mode: python
# End:
