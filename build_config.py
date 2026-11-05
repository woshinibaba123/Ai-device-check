"""Validate the explicitly selected Flutter entrypoint before queueing a build."""
from pathlib import Path

def entrypoint(project, value='lib/main.dart'):
    project=Path(project).resolve()
    if not isinstance(value,str) or not value.strip() or len(value)>256:
        raise ValueError('请填写 Flutter 启动入口，例如 lib/main_eng.dart')
    relative=Path(value.strip())
    if relative.is_absolute() or relative.suffix!='.dart':raise ValueError('启动入口必须是项目内的相对 .dart 路径')
    resolved=(project/relative).resolve()
    try:resolved.relative_to(project)
    except ValueError:raise ValueError('启动入口不能超出源码目录')
    if not resolved.is_file():raise ValueError('未找到启动入口：'+str(relative))
    return str(relative)
