from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    default_params = PathJoinSubstitution([FindPackageShare("iris_bringup"), "config", "iris.params.yaml"])
    params = LaunchConfiguration("params_file")
    simulate = LaunchConfiguration("simulate")
    use_balance = LaunchConfiguration("use_balance")
    motion_backend = LaunchConfiguration("motion_backend")
    poppy_rest_url = LaunchConfiguration("poppy_rest_url")

    return LaunchDescription([
        DeclareLaunchArgument("params_file", default_value=default_params),
        DeclareLaunchArgument("simulate", default_value="true"),
        DeclareLaunchArgument("use_balance", default_value="true"),
        DeclareLaunchArgument("motion_backend", default_value="auto"),
        DeclareLaunchArgument("poppy_rest_url", default_value="http://poppy.local:8080"),
        Node(
            package="iris_motion",
            executable="poppy_driver_node",
            name="poppy_driver_node",
            output="screen",
            parameters=[params, {"simulate": simulate, "control_backend": motion_backend, "rest_base_url": poppy_rest_url}],
        ),
        Node(
            package="iris_motion",
            executable="move_player_node",
            name="move_player_node",
            output="screen",
            parameters=[params],
        ),
        Node(
            package="iris_motion",
            executable="move_recorder_node",
            name="move_recorder_node",
            output="screen",
            parameters=[params],
        ),
        Node(
            package="iris_balance",
            executable="imu_node",
            name="imu_node",
            output="screen",
            parameters=[params, {"simulate": simulate}],
            condition=IfCondition(use_balance),
        ),
        Node(
            package="iris_balance",
            executable="balance_node",
            name="balance_node",
            output="screen",
            parameters=[params],
            condition=IfCondition(use_balance),
        ),
    ])