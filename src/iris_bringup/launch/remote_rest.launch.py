from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    default_params = PathJoinSubstitution([
        FindPackageShare("iris_bringup"),
        "config",
        "iris.remote_rest.example.yaml",
    ])
    full_launch = PathJoinSubstitution([
        FindPackageShare("iris_bringup"),
        "launch",
        "full.launch.py",
    ])

    params = LaunchConfiguration("params_file")
    poppy_rest_url = LaunchConfiguration("poppy_rest_url")
    speech_backend = LaunchConfiguration("speech_backend")
    tts_backend = LaunchConfiguration("tts_backend")
    use_camera = LaunchConfiguration("use_camera")
    use_face = LaunchConfiguration("use_face")

    return LaunchDescription([
        DeclareLaunchArgument("params_file", default_value=default_params),
        DeclareLaunchArgument("poppy_rest_url", default_value="http://poppy.local:8080"),
        DeclareLaunchArgument("speech_backend", default_value="keyboard"),
        DeclareLaunchArgument("tts_backend", default_value="console"),
        DeclareLaunchArgument("use_camera", default_value="true"),
        DeclareLaunchArgument("use_face", default_value="true"),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(full_launch),
            launch_arguments={
                "params_file": params,
                "simulate": "false",
                "use_balance": "false",
                "use_camera": use_camera,
                "use_face": use_face,
                "speech_backend": speech_backend,
                "tts_backend": tts_backend,
                "motion_backend": "rest",
                "poppy_rest_url": poppy_rest_url,
            }.items(),
        ),
    ])
