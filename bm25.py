import click
import json
from operations import (
    run_reset,
    # run_rank,
    run_index
)


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



def parse_table_name(table: str) -> tuple[str,str]:
    # Split by the dot to separate schema and table
    parts = table.split('.')
    
    if len(parts) > 2:
        raise ValueError(f"Invalid table identifier format: {table}")

    schema = None
    if len(parts) > 1:
        schema, table = parts
    else:
        table = parts[0] 

    return schema, table



@click.group(
    cls=OperationGroup,
    options_metavar="[OPTIONS]",
    subcommand_metavar="OPERATION [ARGS]..."
)
def cli():
    pass



def common_options(f):
    f = click.option("-u", "--url", required=True, help="CockroachDB connection URL")(f)
    f = click.option("-t", "--table", required=True, help="Target table name")(f)
    f = click.option("-i", "--input", "input_col", required=True, help="Column containing input text")(f)
    f = click.option("-v", "--verbose", is_flag=True, help="Verbose output (used for debugging)")(f)
    return f



@cli.command(short_help="Reset BM25 stats.")
@common_options
@click.option("-o", "--output", "output_col", required=True,
                help="Column to store the vector")
@click.option("-w", "--workers", default=1, type=int,
                help="Number of parallel workders to use (default: 1)")
@click.option("-b", "--batch-size", default=1000, type=int, help="Rows to process per batch")
@click.option("-n", "--num-batches", default=1, type=int,
              help="Number of batches to process before exiting (default: 1)")
@click.option("-F", "--follow", is_flag=True,
              help="Keep running: keep vectorizing new NULL rows indefinitely")
@click.option("--max-idle", default=60.0, type=float,
              help="Max idle time before exit, in MINUTES (0 = no idle limit)")
@click.option("--min-idle", default=15.0, type=float,
              help="Initial idle backoff between empty scans, in SECONDS")
@click.option("-p", "--progress", is_flag=True, help="Show progress bar")
def reset(
    url,
    table,
    input_col,
    output_col,
    workers,
    batch_size,
    num_batches,
    follow,
    max_idle,
    min_idle,
    verbose,
    progress
):

    args = {
        "url": url,
        "table": table,
        "input": input_col,
        "output": output_col,
        "verbose": verbose,
        "progress": progress,
        "workers": workers,
        "batch_size": batch_size,
        "num_batches": num_batches,
        "follow": follow,
        "max_idle": max_idle,
        "min_idle": min_idle
    }

    # print(json.dumps(args, indent=2))
    run_reset(args)



@cli.command(short_help="Build BM25 index")
@common_options
@click.option("-b", "--batch-size", default=1000, type=int, help="Rows to process per batch")
@click.option("-n", "--num-batches", default=1, type=int,
              help="Number of batches to process before exiting (default: 1)")
def index(
    url,
    table,
    input_col,
    batch_size,
    num_batches,
    verbose
):

    args = {
        "url": url,
        "table": table,
        "input": input_col,
        "verbose": verbose,
        "batch_size": batch_size,
        "num_batches": num_batches,
    }

    run_index(args)




@cli.command(short_help="Run BM25 ranking.")
@common_options
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
    # run_rank(args)




if __name__ == "__main__":
    cli()
