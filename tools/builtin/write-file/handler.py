def run(arguments, context):
    path = context.workspace_path(arguments['path'])
    content = arguments['content']
    if len(content.encode()) > 64000:
        raise ValueError('Text artifacts are limited to 64 KB.')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return {'path': arguments['path'], 'bytes': len(content.encode())}
