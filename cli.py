#!/usr/bin/env python3
"""
CLI interface for the transaction importer.
"""

import re
from decimal import Decimal, InvalidOperation

import click

from core.importer import TransactionImporter
from core.models import ChildTransaction, DatabaseManager, Transaction


def evaluate_expression(expression: str) -> Decimal:
    """
    Evaluate a simple arithmetic expression containing numbers, +, -, *, and /.

    Args:
        expression: String like "1+2.3" or "10-3.5+2*3/4"

    Returns:
        Decimal result of the arithmetic expression

    Raises:
        ValueError: If the expression is invalid or contains unsupported operations
    """
    # Remove all whitespace
    expression = expression.replace(" ", "").strip()

    # Validate expression contains only allowed characters
    if not re.match(r"^[\d+*./-]+[\d.]$", expression):
        raise ValueError(
            "Expression must contain only numbers, ., +, -, *, /, and must be a valid arithmetic expression"
        )

    # Split on the operators while preserving them
    parts = re.split(r"([+*/-])", expression)

    if not parts or parts[0] == "":
        raise ValueError("Invalid expression")

    # Wrap the values in "Decimal({value})"
    new_parts = []
    for part in parts:
        if len(part) > 0 and part[0] not in {"+", "-", "*", "/"}:
            new_parts.append(f"Decimal('{part}')")
        else:
            new_parts.append(part)

    expression = " ".join(new_parts)
    return Decimal(eval(expression))


def interactive_split(transaction):
    """
    Interactively handle transaction processing.

    Args:
        transaction: The transaction to process
        parent_id: The UUID of the parent transaction (optional, can be set later)

    Returns:
        List of child transactions, None to keep original, empty list to skip, or string for new category
    """
    print(f"\nTransaction: {transaction.description}")
    print(f"Amount: {transaction.amount}")
    print(f"Original Category: {transaction.category}")

    while True:
        choice = input(
            "\nEnter a new category or:\n"
            "s - Split\n"
            "x - Ignore / Hide\n"
            "[Return] - Keep the category\n"
            "Choice: "
        ).strip()

        if choice == "s":
            return create_child_transactions(transaction)
        elif choice == "":
            return []  # No children, keep original category
        elif choice == "x":
            return None  # None means ignore / hide transaction
        else:
            return choice  # new category


def create_child_transactions(
    transaction: Transaction, parent_id: str = None
) -> list[ChildTransaction] | None:
    """Helper method to create child transactions interactively."""
    children = []
    sign = -1 if transaction.amount < 0 else 1
    original_amount = abs(transaction.amount)
    remaining_amount = original_amount

    type = "expense" if transaction.amount < 0 else "income"
    print(f"\nSplitting {type}: {transaction.description}")
    print(f"Total amount: ${abs(transaction.amount)}")

    while remaining_amount > Decimal(0):
        print(f"\nRemaining amount: ${remaining_amount}")

        # Get amount for this child
        while True:
            try:
                amount_str = input(
                    "Enter amount for this split (or empty for the rest): "
                ).strip()
                if amount_str == "":
                    amount = remaining_amount
                else:
                    # Try to evaluate as arithmetic expression first
                    try:
                        amount = evaluate_expression(amount_str)
                    except ValueError as e:
                        print(e)
                        continue

                if amount > abs(remaining_amount):
                    print(
                        f"Amount cannot exceed remaining amount (${abs(remaining_amount)})."
                    )
                    continue

                break  # amount is good
            except (ValueError, InvalidOperation):
                print(
                    "Invalid amount. Please enter a valid number or expression (e.g., '1+2.3')."
                )

        # Get category for this child
        category = input("Enter category for this split: ").strip()
        if not category:
            category = transaction.category

        # Create child transaction (parent_id will be set later)
        child = ChildTransaction(
            parent_id or "",  # Use empty string if parent_id is None
            amount * sign,
            category,
            transaction.description,
            transaction.date,
        )
        children.append(child)

        remaining_amount -= amount

        if abs(remaining_amount) <= Decimal("0.01"):
            break

    # If no children were created, return None to keep original
    if not children:
        return None

    return children


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
        skipped_count = 0

        for transaction in transactions:
            if importer.db_manager.transaction_exists(transaction):
                skipped_count += 1
            else:
                parent_id = importer.import_transaction(transaction)
                if parent_id:
                    imported_count += 1

        click.echo(
            f"Successfully imported {imported_count} transactions, {skipped_count} duplicates skipped"
        )

    elif interactive:
        click.echo("Importing transactions interactively...")

        for i, transaction in enumerate(transactions, 1):
            click.echo(f"\n[{i}/{len(transactions)}] Processing transaction...")

            # Check if transaction already exists
            if importer.db_manager.transaction_exists(transaction):
                click.echo(
                    f"{transaction.date} {transaction.amount} {transaction.description} Already imported"
                )
                continue

            # Get user input for splitting/changing category if callback is provided
            result = interactive_split(transaction)

            children = None
            if isinstance(result, list):
                if len(result) != 0:  # Add children
                    transaction.is_split = True
                    transaction.category = None
                    children = result
                else:  # Keep original category
                    pass
            elif isinstance(result, str):  # Change category
                transaction.category = result
            elif result is None:  # Empty list means skip
                transaction.is_hidden = True

            # Import transaction with interactive processing
            transaction_id = importer.import_transaction(transaction)

            # Add children if any were created
            if children:
                for child in children:
                    # Set the parent_id now that we have it
                    child.parent_id = transaction_id
                    importer.import_child_transaction(child)

            # Transaction was imported successfully
            click.echo("✓ Transaction imported")


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
            click.echo(f"{i}. ${child['amount']:.2f}\t{child['category']}")
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


@cli.command()
@click.argument("month", type=str)
@click.argument("output_file", type=click.Path())
@click.option(
    "--db",
    "db_path",
    default="transactions.db",
    help="Database file path (default: transactions.db)",
)
@click.option("--include-hidden", is_flag=True, help="Include hidden transactions")
def export_month(month, output_file, db_path, include_hidden):
    """Export transactions for a given month as CSV.

    Split transactions are replaced by their child transactions.
    """
    import csv
    from datetime import datetime

    # Validate month format
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        click.echo("Error: Month must be in YYYY-MM format (e.g., 2025-06)")
        return

    db_manager = DatabaseManager(db_path)

    # Get all transactions for the month
    all_transactions = db_manager.get_all_parent_transactions(
        include_hidden=include_hidden
    )

    # Filter transactions for the specified month
    month_transactions = []
    for transaction in all_transactions:
        transaction_date = datetime.strptime(transaction["date"], "%m/%d/%Y")
        if transaction_date.strftime("%Y-%m") == month:
            month_transactions.append(transaction)

    if not month_transactions:
        click.echo(f"No transactions found for {month}")
        return

    # Prepare CSV data
    csv_rows = []
    for transaction in month_transactions:
        # Check if transaction is split
        if transaction["is_split"]:
            # Get child transactions and export them instead
            children = db_manager.get_child_transactions(transaction["id"])
            for child in children:
                csv_rows.append(
                    {
                        "Date": child["date"],
                        "Amount": f"${child['amount']:.2f}",
                        "Description": child["description"],
                        "Category": child["category"],
                    }
                )
        else:
            # Export the parent transaction
            csv_rows.append(
                {
                    "Date": transaction["date"],
                    "Amount": f"${transaction['amount']:.2f}",
                    "Description": transaction["description"],
                    "Category": transaction["category"],
                }
            )

    # Write CSV file
    with open(output_file, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["Date", "Amount", "Description", "Category"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        writer.writeheader()
        for row in csv_rows:
            writer.writerow(row)

    click.echo(f"Exported {len(csv_rows)} transactions to {output_file}")
    click.echo(f"Original transactions: {len(month_transactions)}")
    click.echo(
        f"Split transactions replaced with {len(csv_rows) - len(month_transactions) + 1} child transactions"
    )


if __name__ == "__main__":
    cli()
