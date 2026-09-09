def run(arguments, context):
    with context.workspace_path(arguments['path']).open('r', encoding='utf-8') as handle:
        return {'content': handle.read(8000)}
