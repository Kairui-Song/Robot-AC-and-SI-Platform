from setuptools import find_packages
from setuptools import setup

setup(
    name='linglong_control_tools',
    version='0.3.0',
    packages=find_packages(
        include=('linglong_control_tools', 'linglong_control_tools.*')),
)
