# -*- coding: utf-8 -*-
'''
This returner logs the package status update to /var/log/debdeploy.log
'''

import datetime

def returner(ret):
    with open("/var/log/debdeploy.log", "a") as log:
        if ret['return'].has_key('aptlog'):
            indented = [datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S ") + l for l in ret['return']['aptlog'].splitlines()]
            log.write("\n".join(indented))

# Local variables:
# mode: python
# End:
