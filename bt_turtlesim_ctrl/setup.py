from glob import glob

from setuptools import setup

package_name = "bt_turtlesim_ctrl"

setup(
    name=package_name,
    version="1.0.0",
    packages=[package_name],
    data_files=[
        # ament resource index marker
        (
            "share/ament_index/resource_index/packages",
            ["resource/" + package_name],
        ),
        # package manifest
        ("share/" + package_name, ["package.xml"]),
        # launch files (explicit pattern so launch/__pycache__ is never installed)
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
        # behavior-tree structures: the two .xml trees + the .btproj
        ("share/" + package_name + "/bt_structures", glob("bt_structures/*")),
        # parameter configs
        ("share/" + package_name + "/config", glob("config/*")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Mahdi Rezapour",
    maintainer_email="mahdi.rezapour@dfki.de",
    description=(
        "BTEng (Python) prey-hunting controller for turtlesim with a "
        "ZmqPublisher live stream on port 2667."
    ),
    license="MIT",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "turtle_controller = bt_turtlesim_ctrl.turtle_controller_node:main",
            "turtle_spawner = bt_turtlesim_ctrl.turtle_spawner_node:main",
        ],
    },
)
