# -*- coding: utf-8 -*-

from __future__ import print_function

import salt.client
import yaml
import sys

class DebDeployUpdateSpec(object):
    '''
    Each update is described in a YAML file, see docs/readme.txt for the data
    format.
    '''

    source = ""
    comment = ""
    update_type = ""
    fixes = {}
    libraries = []
    legit_type = ['tool', 'daemon-direct', 'daemon-disrupt', 'daemon-cluster', 'reboot', 'reboot-cluster', 'library']

    def __init__(self, updatespec, supported_distros):
        '''
        Parse an update spec file.

        updatespec        : Filename of the update spec file (string)
        supported_distros : These are the distro codenames for which a fixed version can be provided (list of strings)
        '''

        try:
            with open(updatespec, "r") as stream:
                updatefile = yaml.load(stream)

        except IOError:
            print("Error: Could not open", updatespec)
            sys.exit(1)

        except yaml.scanner.ScannerError, e:
            print("Invalid YAML file:")
            print(e)
            sys.exit(1)

        if not updatefile.has_key("source"):
            print("Invalid YAML file, you need to specify the source package using the 'source' stanza, see the annotated example file for details")
            sys.exit(1)
        else:
            self.source = updatefile["source"]

        if not updatefile.has_key("update_type"):
            print("Invalid YAML file, you need to specify the type of update using the 'update_type' stanza, see the annotated example file for details")
            sys.exit(1)
        else:
            if updatefile["update_type"] not in self.legit_type:
                print("Invalid YAML file, invalid 'update_type'")
                sys.exit(1)
            self.update_type = updatefile["update_type"]

        if updatefile.has_key("comment"):
            self.comment = updatefile["comment"]

        if updatefile.has_key("libraries"):
            self.libraries = updatefile["libraries"]

        if not updatefile.has_key("fixes"):
            print("Invalid YAML file, you need to specify at least one fixed version using the 'fixes' stanza, see the annotated example file for details")
            sys.exit(1)
        else:
            for i in updatefile["fixes"]:
                if len(supported_distros.keys()) >= 1:
                    self.fixes[i] = updatefile["fixes"].get(i)
                else:
                    print("Invalid YAML file,", i, "is not a supported distribution. You need to activate it in /deb/debdeploy.conf")
                    sys.exit(1)

# Local variables:
# mode: python
# End:
