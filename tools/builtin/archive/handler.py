from runtime.archives import process, pack

def run(arguments, context):
    return pack(arguments, context) if arguments.get("action") == "pack" else process(arguments, context)
