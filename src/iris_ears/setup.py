from setuptools import find_packages, setup

package_name = "iris_ears"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Iris Team",
    maintainer_email="iris@example.com",
    description="Speech input for Iris",
    license="MIT",
    entry_points={
        "console_scripts": [
            "speech_node = iris_ears.speech_node:main",
        ],
    },
)