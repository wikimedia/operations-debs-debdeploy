# -*- coding: utf-8 -*-

from __future__ import print_function

import ConfigParser, sys

class DebDeployConfig(object):
    '''
    Class to read/provide the system-wide configuration of the debdeploy master component.
    It contains the following variables:

    supported_distros: List of strings of supported distros (per Debian/Ubuntu codename)
    '''
    supported_distros = {}
    debug = False
    library_hints = {}

    def __init__(self, configfile):
        config = ConfigParser.ConfigParser()
        if len(config.read(configfile)) == 0:
            print("/etc/debdeploy.conf doesn't exist, you need to create it.")
            print("See /usr/share/doc/debdeploy-master/examples/debdeploy.conf")
            sys.exit(1)

        if not config.has_section("distros"):
            print("Could not read list of supported distributions, make sure", configfile, "contains a section [distros]")
            sys.exit(1)

        for distro in config.options("distros"):
            self.supported_distros[distro] = []
            self.supported_distros[distro].append([x.strip() for x in config.get("distros", distro).split(",")])

        if len(self.supported_distros) < 1:
            print("You need to specify at least one supported distribution in /etc/debdeploy.conf")
            sys.exit(1)

        if config.has_section("libraries"):
            for library in config.options("libraries"):
                self.library_hints[library] = []
                for i in config.get("libraries", library).split(","):
                    self.library_hints[library].append(i.strip())

        if config.has_section("logging") and config.has_option("logging", "debug"):
            if config.getboolean("logging", "debug"):
                self.debug = True

conf = DebDeployConfig("/etc/debdeploy.conf")

# Local variables:
# mode: python
# End:





