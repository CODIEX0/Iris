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
    use_face = LaunchConfiguration("use_face")
    speech_backend = LaunchConfiguration("speech_backend")
    tts_backend = LaunchConfiguration("tts_backend")

    return LaunchDescription([
        DeclareLaunchArgument("params_file", default_value=default_params),
        DeclareLaunchArgument("simulate", default_value="true"),
        DeclareLaunchArgument("use_face", default_value="true"),
        DeclareLaunchArgument("speech_backend", default_value="keyboard"),
        DeclareLaunchArgument("tts_backend", default_value="console"),
        Node(
            package="iris_eyes",
            executable="vision_node",
            name="vision_node",
            output="screen",
            parameters=[params, {"simulate": simulate}],
        ),
        Node(
            package="iris_ears",
            executable="speech_node",
            name="speech_node",
            output="screen",
            parameters=[params, {"backend": speech_backend}],
        ),
        Node(
            package="iris_mouth",
            executable="tts_node",
            name="tts_node",
            output="screen",
            parameters=[params, {"backend": tts_backend}],
        ),
        Node(
            package="iris_face",
            executable="face_node",
            name="face_node",
            output="screen",
            parameters=[params],
            condition=IfCondition(use_face),
        ),
    ])