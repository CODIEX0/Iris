import glob
import os
from setuptools import find_packages, setup

package_name = "iris_motion"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        (os.path.join("share", package_name), ["package.xml"]),
        (os.path.join("share", package_name, "moves"), glob.glob("moves/*.json")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Iris Team",
    maintainer_email="iris@example.com",
    description="Poppy motion bridge",
    license="MIT",
    entry_points={
        "console_scripts": [
            "poppy_driver_node = iris_motion.poppy_driver_node:main",
            "move_player_node = iris_motion.move_player_node:main",
            "move_recorder_node = iris_motion.move_recorder_node:main",
        ],
    },
)