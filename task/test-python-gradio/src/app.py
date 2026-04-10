import gradio as gr
import argparse

def greet(name):
    return "Hello " + name + "!"


def parse_cli_args():
    parser = argparse.ArgumentParser(description="Run Gradio demo server")
    parser.add_argument(
        "--server-name",
        default="127.0.0.1",
        help="Server host name or IP address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--server-port",
        type=int,
        default=7860,
        help="Server port (default: 7860)",
    )
    args = parser.parse_args()

    if not 1 <= args.server_port <= 65535:
        parser.error("--server-port must be between 1 and 65535")

    return args

demo = gr.Interface(fn=greet, inputs="text", outputs="text")

if __name__ == "__main__":
    cli_args = parse_cli_args()
    demo.launch(server_name=cli_args.server_name, server_port=cli_args.server_port)
