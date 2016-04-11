# -*- coding: utf-8 -*-
'''
Module for deploying DEB packages on wide scale
'''

import logging, pickle, subprocess, os, re
import logging.handlers

import ConfigParser
import salt.utils
import salt.config
import salt.loader
import salt.modules.aptpkg
#from salt.modules import aptpkg
from debian import deb822

from salt.modules.debdeploy_restart import Checkrestart
from salt.exceptions import (
    CommandExecutionError, MinionError, SaltInvocationError
)

log = logging.getLogger(__name__)

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
                    if subprocess.check_call(handler) == 0:
                        results[program] = 0
                    else:
                        results[program] = 1
                except CalledProcessError:
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

        log.info("Restarting " + service + " for " + program)
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
    blacklisted_packages = []

    installed_distro = grains['oscodename']
    if versions.get(installed_distro, None) == None:
        log.info("Update doesn't apply to the installed distribution (" + installed_distro + ")")
        return {}

    if os.path.exists("/etc/debdeploy-minion.conf"):
        config = ConfigParser.ConfigParser()
        config.read("/etc/debdeploy-minion.conf")

        if config.has_section("blacklist-" + installed_distro):
            if config.has_option("blacklist-" + installed_distro, source):
                blacklisted_packages = [x.strip() for x in config.get("blacklist-" + installed_distro, source).split(",")]
    log.info("Packages blacklisted for upgrades: " + str(blacklisted_packages))

    # Detect all locally installed binary packages of a given source package
    # The only resource we can use for that is parsing the /var/lib/dpkg/status
    # file. The format is a bit erratic: The Source: line is only present for
    # binary packages not having the same name as the binary package
    installed_binary_packages = []
    for pkg in deb822.Packages.iter_paragraphs(file('/var/lib/dpkg/status')):

        # skip packages in deinstalled status ("rc" in dpkg). These are not relevant for
        # upgrades and cause problems when binary package names have changed (since package
        # installations are forced with a specific version which is not available for those
        # outdated binary package names)
        installation_status = pkg['Status'].split()[0]
        if installation_status == "deinstall":
            continue

        if pkg.has_key('Package') and pkg.get('Package') in blacklisted_packages:
            log.info('Package ' + pkg.get('Package') + ' has been blacklisted for installation')
            continue

        # Source packages which have had a binNMU have a Source: entry with the source
        # package version in brackets, so strip these
        # If no Source: entry is present in /var/lib/dpkg/status, then the source package
        # name is identical to the binary package name
        if pkg.has_key('Source') and re.sub(r'\(.*?\)', '', pkg['Source']).strip() == source:
            installed_binary_packages.append({pkg['Package'] : versions[installed_distro]})
        elif pkg.has_key('Package') and pkg['Package'] == source:
            installed_binary_packages.append({pkg['Package'] : versions[installed_distro]})
    log.debug("Installed binary packages for " + source + ": " + str(installed_binary_packages))

    if len(installed_binary_packages) == 0:
        log.info("No binary packages installed for source package " + source)
        return {}

    if update_type == "library":
        pending_restarts_pre = Checkrestart().get_programs_to_restart()
        log.debug("Packages needing a restart prior to the update:" + str(pending_restarts_pre))

    old = list_pkgs()

    log.warn("Refreshing apt package database")
    log.info("Refreshing apt package database")
    __salt__['pkg.refresh_db']

    apt_call = install_pkgs(installed_binary_packages)

    new = list_pkgs()

    if update_type == "library":
        pending_restarts_post = Checkrestart().get_programs_to_restart()
        log.debug("Packages needing a restart after to the update:" + str(pending_restarts_post))

    old_keys = set(old.keys())
    new_keys = set(new.keys())

    additions = []
    removals = []
    updated = []
    restarts = []
    new_restarts = []

    if update_type == "library":
        restarts = list(pending_restarts_post)
        new_restarts = list(pending_restarts_post.difference(pending_restarts_pre))

    for i in new_keys.difference(old_keys):
        additions.append[i]
    for i in old_keys.difference(new_keys):
        removals.append[i]
    intersect = old_keys.intersection(new_keys)
    modified = {x : (old[x], new[x]) for x in intersect if old[x] != new[x]}

    log.info("Newly installed packages:" + str(additions))
    log.info("Removed packages: "  + str(removals))
    log.info("Modified packages: " + str(modified))
    log.info("Packages needing a restart: " + str(restarts))
    log.info("New packages needing a restart: " + str(new_restarts))

    r = {}
    r["additions"] = additions
    r["removals"] = removals
    r["updated"] = modified
    r["new_restart"] = new_restarts
    r["restart"] = restarts
    r["aptlog"] = str(apt_call['stdout'])
    r["apterrlog"] = str(apt_call['stderr'])
    r["aptreturn"] = apt_call['retcode']

    jobid = kwargs.get('__pub_jid')
    with open("/var/lib/debdeploy/" + jobid + ".job", "w") as jobfile:
        pickle.dump(r, jobfile)

    return r


def rollback(jobid):
    '''
    Roll back a software update specified by a Salt job ID

    '''
    with open("/var/lib/debdeploy/" + jobid + ".job", "r") as jobfile:
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
    old_keys = set(old.keys())
    new_keys = set(new.keys())

    additions = []
    removals = []
    updated = []
    restarts = []

    for i in new_keys.difference(old_keys):
        additions.append[i]
    for i in old_keys.difference(new_keys):
        removals.append[i]
    intersect = old_keys.intersection(new_keys)
    modified = {x : (old[x], new[x]) for x in intersect if old[x] != new[x]}

    log.info("Newly installed packages:" + str(additions))
    log.info("Removed packages: "  + str(removals))
    log.info(modified)

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
