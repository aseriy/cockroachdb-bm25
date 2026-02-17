import click
import json
from operations import run_rank


class OperationGroup(click.Group):
    def format_commands(self, ctx, formatter):
        # This overrides the 'Commands' header
        commands = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None or cmd.hidden:
                continue
            commands.append((subcommand, cmd.get_short_help_str()))

        if commands:
            with formatter.section("Operations"):
                formatter.write_dl(commands)



@click.group(
    cls=OperationGroup,
    options_metavar="[OPTIONS]",
    subcommand_metavar="OPERATION [ARGS]..."
)
def cli():
    pass



def shared_db_options(f):
    f = click.option("-u", "--url", required=True, help="CockroachDB connection URL")(f)
    f = click.option("-t", "--table", required=True, help="Target table name")(f)
    f = click.option("-i", "--input", "input_col", required=True, help="Column containing input text")(f)
    f = click.option("-o", "--output", "output_col", required=True, help="Column to store the vector")(f)
    f = click.option("-v", "--verbose", is_flag=True, help="Verbose output (used for debugging)")(f)
    return f



@cli.command(short_help="Vectorize rows in CockroachDB using a specified encoding model.")
@shared_db_options
def rank(
    url,
    table,
    input_col,
    output_col,
    verbose
):

    args = {
        "url": url,
        "table": table,
        "input": input_col,
        "output": output_col,
        "verbose": verbose
    }

    # print(json.dumps(args, indent=2))
    run_rank(args)


# @cli.command(short_help="Run similarity search")
# @shared_db_options
# @click.option("-l", "--limit", default=10, type=int, help="Number of the closest matches (default: 10)")
# @click.argument("text", required=False)
# def search(
#         url,
#         table,
#         input_col,
#         output_col,
#         limit,
#         model,
#         verbose,
#         text
# ):

#     args = {
#         "url": url,
#         "table": table,
#         "source": input_col,
#         "embedding": output_col,
#         "limit": limit,
#         "model": model,
#         "verbose": verbose,
#         "text": text
#     }

#     run_search(args)




# @cli.group(short_help="Explore available vector embedding models.")
# def model():
#     pass


# @model.command(short_help="List available vector embedding models.")
# def list():
#     args = {}
#     run_model_list(args)



# @model.command(short_help="Describe spefic model.")
# @click.argument("model", required=True)
# def desc(model: str):
#     args = {
#         "model": model
#     }
#     run_model_desc(args)





if __name__ == "__main__":
    cli()
