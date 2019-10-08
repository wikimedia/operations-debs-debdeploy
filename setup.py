#!/usr/bin/env python
from setuptools import find_packages, setup

# Required dependencies
install_requires = [
    'psutil',
    'PyYAML',
    'python-debian',
]

setup(
    description='Debian package deployment tool',
    install_requires=install_requires,
    license='GPLv3+',
    name='debdeploy',
    platforms=['GNU/Linux'],
)
