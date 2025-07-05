#!/usr/bin/env python3
"""
CLI interface for the transaction importer.
"""

import click
from core.models import DatabaseManager
from core.importer import TransactionImporter, ChildTransactionCreator


@click.group()
def cli():
    """Transaction Importer CLI - Import and manage financial transactions."""
    pass


@cli.command()
@click.argument("csv_file", type=click.Path(exists=True))
@click.option(
    "--db",
    "db_path",
    default="transactions.db",
    help="Database file path (default: transactions.db)",
)
@click.option(
    "--interactive",
    is_flag=True,
    help="Interactively split transactions into child transactions",
)
@click.option(
    "--auto",
    is_flag=True,
    help="Automatically import without creating child transactions",
)
def import_csv(csv_file, db_path, interactive, auto):
    """Import transactions from a CSV file."""
    if not interactive and not auto:
        click.echo("Error: Must specify either --interactive or --auto")
        return

    # Initialize database and importer
    db_manager = DatabaseManager(db_path)
    importer = TransactionImporter(db_manager)

    # Load transactions
    click.echo(f"Loading transactions from {csv_file}...")
    transactions = importer.load_transactions_from_csv(csv_file)
    transactions.reverse()
    click.echo(f"Found {len(transactions)} non-pending transactions")

    # Import transactions
    if auto:
        click.echo("Importing transactions automatically...")
        imported_count = 0
        duplicate_count = 0

        for transaction in transactions:
            if importer.db_manager.transaction_exists(transaction):
                duplicate_count += 1
            else:
                parent_id = importer.import_transaction(transaction)
                if parent_id:
                    imported_count += 1

        click.echo(
            f"Successfully imported {imported_count} transactions, {duplicate_count} duplicates skipped"
        )

    elif interactive:
        click.echo("Importing transactions interactively...")
        imported_count = 0
        skipped_count = 0
        duplicate_count = 0

        for i, transaction in enumerate(transactions, 1):
            click.echo(f"\n[{i}/{len(transactions)}] Processing transaction...")

            # Check if transaction already exists
            if importer.db_manager.transaction_exists(transaction):
                click.echo(
                    f"{transaction.date} {transaction.amount} {transaction.description} Already imported"
                )
                duplicate_count += 1
                continue

            # Import parent transaction first
            parent_id = importer.import_transaction(transaction)

            # Handle child transaction creation
            children = ChildTransactionCreator.interactive_split(transaction, parent_id)

            if children is None:
                # Keep original category, no children
                imported_count += 1
                click.echo("✓ Transaction imported with original category")
            elif children == []:
                importer.db_manager.mark_transaction_as_hidden(parent_id)
                click.echo("✗ Transaction marked as hidden")
                skipped_count += 1
            elif isinstance(children, str):
                new_category = children
                importer.db_manager.update_transaction_category(parent_id, new_category)
                click.echo(f"✓ Transaction category changed to: {new_category}")
                imported_count += 1
            else:
                # Add children
                for child in children:
                    importer.db_manager.insert_child_transaction(child)
                # Mark the parent transaction as split
                importer.db_manager.mark_transaction_as_split(parent_id)
                imported_count += 1
                click.echo(
                    f"✓ Transaction split into {len(children)} child transactions"
                )

        click.echo(
            f"\nImport complete: {imported_count} imported, {skipped_count} hidden, {duplicate_count} duplicates"
        )


@cli.command()
@click.option(
    "--db",
    "db_path",
    default="transactions.db",
    help="Database file path (default: transactions.db)",
)
@click.option(
    "--limit", default=20, help="Number of transactions to show (default: 20)"
)
@click.option("--include-hidden", is_flag=True, help="Include hidden transactions")
def list_transactions(db_path, limit, include_hidden):
    """List imported transactions."""
    db_manager = DatabaseManager(db_path)
    transactions = db_manager.get_all_parent_transactions(include_hidden=include_hidden)

    if not transactions:
        click.echo("No transactions found in database.")
        return

    click.echo(f"Found {len(transactions)} transactions:")
    click.echo("-" * 80)

    for i, transaction in enumerate(transactions[:limit], 1):
        click.echo(f"{i}. ID: {transaction['id'][:8]}...")
        click.echo(f"   Date: {transaction['date']}")
        click.echo(f"   Description: {transaction['description']}")
        click.echo(f"   Amount: ${transaction['amount']:.2f}")
        click.echo(f"   Category: {transaction['category']}")
        click.echo(f"   Account: {transaction['account']}")
        if transaction["is_hidden"]:
            click.echo("  Status: HIDDEN")
        if transaction["is_split"]:
            click.echo("  Status: SPLIT")

        # Show child transactions
        children = db_manager.get_child_transactions(transaction["id"])
        if children:
            click.echo(f"   Children ({len(children)}):")
            for child in children:
                click.echo(f"     - ${child['amount']:.2f} ({child['category']})")
        else:
            click.echo("   No child transactions")

        click.echo()


@cli.command()
@click.argument("transaction_id")
@click.option(
    "--db",
    "db_path",
    default="transactions.db",
    help="Database file path (default: transactions.db)",
)
def show_transaction(transaction_id, db_path):
    """Show details of a specific transaction."""
    db_manager = DatabaseManager(db_path)
    transaction = db_manager.get_parent_transaction(transaction_id)

    if not transaction:
        click.echo(f"Transaction with ID {transaction_id} not found.")
        return

    click.echo("Transaction Details:")
    click.echo("-" * 40)
    click.echo(f"ID: {transaction['id']}")
    click.echo(f"Date: {transaction['date']}")
    click.echo(f"Description: {transaction['description']}")
    click.echo(f"Amount: ${transaction['amount']:.2f}")
    click.echo(f"Category: {transaction['category']}")
    click.echo(f"Institution: {transaction['institution']}")
    click.echo(f"Account: {transaction['account']}")
    click.echo(f"Hidden: {transaction['is_hidden']}")
    click.echo(f"Split: {transaction['is_split']}")

    # Show child transactions
    children = db_manager.get_child_transactions(transaction["id"])
    if children:
        click.echo(f"\nChild Transactions ({len(children)}):")
        click.echo("-" * 40)
        for i, child in enumerate(children, 1):
            click.echo(f"{i}. Amount: ${child['amount']:.2f}")
            click.echo(f"   Category: {child['category']}")
            click.echo(f"   Description: {child['description']}")
            click.echo(f"   Date: {child['date']}")
            click.echo()
    else:
        click.echo("\nNo child transactions")


@cli.command()
@click.option(
    "--db",
    "db_path",
    default="transactions.db",
    help="Database file path (default: transactions.db)",
)
def stats(db_path):
    """Show database statistics."""
    db_manager = DatabaseManager(db_path)
    all_transactions = db_manager.get_all_parent_transactions(include_hidden=True)

    if not all_transactions:
        click.echo("No transactions found in database.")
        return

    # Count transactions with children
    transactions_with_children = 0
    total_children = 0
    hidden_transactions = 0
    split_transactions = 0

    for transaction in all_transactions:
        if transaction["is_hidden"]:
            hidden_transactions += 1
        if transaction["is_split"]:
            split_transactions += 1
            children = db_manager.get_child_transactions(transaction["id"])
            if children:
                transactions_with_children += 1
                total_children += len(children)

    total_transactions = len(all_transactions)
    visible_transactions = total_transactions = hidden_transactions

    click.echo("Database Statistics:")
    click.echo("-" * 30)
    click.echo(f"Total transactions: {total_transactions}")
    click.echo(f"Visible transactions: {visible_transactions}")
    click.echo(f"Hidden transactions: {hidden_transactions}")
    click.echo(f"Split transactions: {split_transactions}")
    click.echo(f"Transactions with children: {transactions_with_children}")
    click.echo(f"Total child transactions: {total_children}")
    if transactions_with_children > 0:
        click.echo(
            f"Average children per split: {total_children / transactions_with_children:.1f}"
        )
    else:
        click.echo("Average children per split: 0")


@cli.command()
@click.option(
    "--db",
    "db_path",
    default="transactions.db",
    help="Database file path (default: transactions.db)",
)
def init_db(db_path):
    """Initialize the database."""
    DatabaseManager(db_path)
    click.echo(f"Database initialized at {db_path}")


if __name__ == "__main__":
    cli()
