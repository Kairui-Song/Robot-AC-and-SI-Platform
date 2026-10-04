from glob import glob
from setuptools import setup

setup(
    name='arm_control', version='0.1.0', packages=['arm_control'],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/arm_control']),
        ('share/arm_control', ['package.xml']),
        *[('share/arm_control/' + folder, glob(folder + '/*'))
          for folder in ('launch', 'config', 'urdf', 'rviz')],
    ],
    install_requires=['setuptools'], tests_require=['pytest'], zip_safe=True,
    maintainer='Linglong developer', maintainer_email='maintainer@example.com',
    description='ROS 2 EtherCAT left arm control', license='Apache-2.0',
    entry_points={'console_scripts': ['arm_control_node = arm_control.node:main']},
)
