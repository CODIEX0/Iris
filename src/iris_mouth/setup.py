from setuptools import find_packages, setup

package_name = "iris_mouth"

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
    description="TTS and viseme publisher for Iris",
    license="MIT",
    entry_points={
        "console_scripts": [
            "tts_node = iris_mouth.tts_node:main",
        ],
    },
)