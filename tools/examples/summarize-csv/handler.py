import csv


def run(arguments, context):
    with context.workspace_path(arguments['path']).open(newline='', encoding='utf-8') as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames or []
        count = sum(1 for _ in reader)
    return {'row_count': count, 'columns': columns}
