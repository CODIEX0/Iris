import glob
import os
from setuptools import find_packages, setup

package_name = "iris_bringup"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        (os.path.join("share", package_name), ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob.glob("launch/*.launch.py")),
        (os.path.join("share", package_name, "config"), glob.glob("config/*.yaml")),
        (os.path.join("share", package_name, "scripts"), glob.glob("scripts/*.sh")),
        (os.path.join("share", package_name, "systemd"), glob.glob("systemd/*.service")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Iris Team",
    maintainer_email="iris@example.com",
    description="Bringup assets for Iris",
    license="MIT",
)