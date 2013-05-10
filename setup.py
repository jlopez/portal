import os
import re
from setuptools import setup, find_packages

VERSIONFILE = os.path.join('portal', '_version.py')
VSRE = r'^__version__ = [\'"](.*?)[\'"]'

def get_version():
    verstrline = open(VERSIONFILE, 'rt').read()
    mo = re.search(VSRE, verstrline, re.M)
    if mo:
        return mo.group(1)
    else:
        raise RuntimeError(
                "Unable to find version string in %s." % VERSIONFILE)

setup(
    name="portal",
    version=get_version(),
    description="Interact with Apple's Provisioning Portal, stay sane",
    author="Jesus Lopez",
    author_email="jesus@jesusla.com",
    url = "https://www.github.com/jlopez/portal",
    license = "MIT",
    packages=find_packages(),
    include_package_data=True,
    entry_points=dict(
      console_scripts=[
        'portal = portal.cli:main'
      ],
    ),
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.5',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Utilities',
    ]
)
