#! /usr/bin/python
# -*- coding: utf-8 -*-

# TODO:
# reinstate rollback handling
# revamp and readd restart handling

import argparse
import code
import json
import logging
import os
import pkgutil
import signal
import sys
import datetime

from ClusterShell.NodeSet import NodeSet

import cumin

from cumin import backends, query, transport, transports
from debdeploy_conf import *
import pydoc
from debdeploy_updatespec import *


if os.geteuid() != 0:
    print "debdeploy needs to be run as root"
    sys.exit(1)


cumin_config = cumin.Config()
conf = DebDeployConfig("/etc/debdeploy.conf")

if conf.debug:
    logging.basicConfig(filename='/var/log/debdeploy/debdeploy.log',
                        format='%(levelname)s: %(asctime)s : %(funcName)s : %(message)s',
                        level=logging.DEBUG)
else:
    logging.basicConfig(filename='/var/log/debdeploy/debdeploy.log',
                        format='%(levelname)s: %(asctime)s : %(funcName)s : %(message)s',
                        level=logging.INFO)


class logpager:
    threshold = 20  # if pager buffer contains more than <threshold> lines, use the pager

    def __init__(self):
        self.buf = ""

    def add(self, *args):
        for i in args:
            self.buf += str(i)
        self.buf += "\n"

    def add_nb(self, *args):
        for i in args:
            self.buf += str(i)

    def show(self):
        if self.buf.count("\n") > self.threshold:
            pydoc.pager(self.buf)
        else:
            print self.buf


def run_cumin(cmd):
    '''
    Run Cumin and discard the output shown by the transport

    cmd : The Command to be executed
    '''

    with open('/dev/null', 'w') as discard_output:
         oldstdout = sys.stdout
         oldstderr = sys.stderr
         sys.stdout = discard_output
         sys.stderr = discard_output

         worker = transport.Transport.new(cumin_config, logging)
         hosts = query.Query(cumin_config).execute('A:all')

         worker.target = transports.Target(hosts, batch_size=100, batch_sleep=None, logger=logging)
         worker.commands = [cmd]

         worker.timeout = None
         worker.handler = 'sync'
         worker.success_threshold = 0.1
         worker.batch_size = 100
         worker.batch_sleep = None
         exit_code = worker.execute()
         sys.stdout = oldstdout
         sys.stderr = oldstderr

    return worker


def deploy_update(source, update_type, update_file, servergroup, supported_distros, fixes):
    '''
    Initiate a deployment.

    source      : Name of the source package (string)
    update_type : Various types of packages have different outcome, see doc/readme.txt (string)
    update_file : Filename of update specification (string)
    servergroup : The name of the server group (string)
    '''

    update_desc = {}
    update_desc["tool"] = "Non-daemon update, no service restart needed"
    update_desc["daemon-direct"] = "Daemon update without user impact"
    update_desc["daemon-disrupt"] = "Daemon update with service availability impact"
    update_desc["library"] = "Library update, several services might need to be restarted"

    print "Rolling out", source, ":",
    print update_desc[update_type]

    worker = transport.Transport.new(cumin_config, logging)
    hosts = query.Query(cumin_config).execute('A:all')

    cmd = '/usr/bin/debdeploy-deploy --source ' + source + ' --updatespec '

    for distro in fixes:
        if fixes[distro]:
            cmd += str(supported_distros[distro][0][0]) + "_" + str(supported_distros[distro][0][1])
            + "_" + str(fixes[distro]) + " "

    worker.target = transports.Target(hosts, batch_size=100, batch_sleep=None, logger=logging)
    worker.commands = [cmd]

    worker.timeout = None
    worker.handler = 'sync'
    worker.success_threshold = 0.1
    worker.batch_size = 100
    worker.batch_sleep = None

    # with open('/dev/null', 'w') as discard_output:
    #     oldstdout = sys.stdout
    #     sys.stdout = discard_output
    #     exit_code = worker.execute()
    #     sys.stdout = oldstdout

    exit_code = worker.execute()

    out = {}
    for nodeset, output in worker.get_results():
        print output

def detect_restarts(libnames, servergroup, verbose):
    '''
    Query for necessary restarts after a library or interpreter upgrade

    libnames    : A list of library base names, e.g. libssl for
                  /usr/lib/x86_64-linux-gnu/libssl.so.1.0.0 (list of strings)
    servergroup : The name of the server group for which process restarts should be queried (string)
    verbose     : If enabled, the full of hosts needing a restart is shown (boolean)
    '''

    cmd = '/usr/bin/debdeploy-restarts --json --libname '
    for lib in libnames:
        cmd += lib + " "

    worker = run_cumin(cmd)

    restarts_per_lib = {}
    for nodeset, output in worker.get_results():
        msg = str(output)
        hostname = str(nodeset)
        if msg.startswith("OK "):
            restarts = json.loads(msg[3:])
            for library in restarts.keys():
                if not restarts_per_lib.get(library, None):
                    restarts_per_lib[library] = {}

                for program in restarts[library]:
                    if not restarts_per_lib[library].get(program, None):
                        restarts_per_lib[library][program] = []
                    restarts_per_lib[library][program].append(hostname)

    for lib in restarts_per_lib:
        print "Restarts for", lib
        for program in restarts_per_lib[lib]:
            out = "  " + program
            if verbose:
                for host in sorted(restarts_per_lib[lib][program]):
                    out += "\n    " + host
            else:
                out += " (" + str(len(restarts_per_lib[lib][program])) + " hosts)"
            print out

    unreachable_hosts = []
    for node in worker._handler_instance.nodes.itervalues():
        if node.state.is_failed:
            unreachable_hosts.append(node.name)
    if len(unreachable_hosts) > 0:
        print "The following hosts were unreachable:"
        for host in unreachable_hosts:
            print host


def main():
    p = argparse.ArgumentParser(usage="""debdeploy-master [options] command <cmd-option> \n
    The following commands are supported: \n\n
    deploy                      Install a software update, requires --update and --servers \n
    query_restart               Query for necessary restarts after a library or interpreter \n
                                upgrade \n
    rollback                    Rollback a software deployment""")

    p.add_argument("-u", "--update", action="store", type=str, dest="updatefile",
                   help="A YAML file containing the update specification (which source package to \
                   update and the respective fixed versions")
    p.add_argument("-s", "--servers", action="store", type=str, dest="serverlist",
                   help="The group of servers on which the update should be applied")
    p.add_argument("--verbose", action="store_true", dest="verbose",
                   help="Enable verbose output, e.g. show full apt output in status-deploy and \
                   status-rollback")

    p.add_argument("command")
    p.add_argument("command_option", nargs="?", default="unset")

    opt = p.parse_args()

    if opt.command in ("deploy", "rollback", "restart", "query_restart"):
        if not opt.serverlist:
            p.error("You need to provide a server list (-s)")

    if opt.command in ("deploy", "rollback", "query_restart"):
        if not opt.updatefile:
            p.error("You need to provide an update file (-u)")

    if opt.command in ("restart"):
        if not opt.program:
            p.error("You need to provide a program to restart (-p)")

    if opt.command == "deploy":
        update = DebDeployUpdateSpec(opt.updatefile, conf.supported_distros)
        deploy_update(update.source, update.update_type, opt.updatefile, opt.serverlist,
                      conf.supported_distros, update.fixes)

    elif opt.command == "query_restart":
        update = DebDeployUpdateSpec(opt.updatefile, conf.supported_distros)
        detect_restarts(update.libraries, opt.serverlist, opt.verbose)

    elif opt.command == "status-rollback":
        display_status(rollback_mode=True)

    elif opt.command == "rollback":
        rollback(opt.serverlist, opt.updatefile)


if __name__ == '__main__':
    print main()


# Local variables:
# mode: python
# End:
