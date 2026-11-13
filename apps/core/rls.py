from django.db.migrations.operations.base import Operation

POLICY = "store_isolation"
CONDITION = "store_id = NULLIF(current_setting('app.store_id', true), '')::uuid"


class EnableRowLevelSecurity(Operation):
    """Migration operation: isolate a store-scoped table by `store_id`.

    FORCE makes the policy apply to the table owner too (the app role owns its tables).
    """

    reduces_to_sql = True
    reversible = True

    def __init__(self, model_name: str):
        self.model_name = model_name

    def state_forwards(self, app_label, state):
        pass

    def _table(self, app_label, state):
        return state.apps.get_model(app_label, self.model_name)._meta.db_table

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        table = schema_editor.quote_name(self._table(app_label, to_state))
        schema_editor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        schema_editor.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        schema_editor.execute(
            f"CREATE POLICY {POLICY} ON {table} USING ({CONDITION}) WITH CHECK ({CONDITION})"
        )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        table = schema_editor.quote_name(self._table(app_label, from_state))
        schema_editor.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        schema_editor.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        schema_editor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    def describe(self):
        return f"Enable row-level security on {self.model_name}"

    def deconstruct(self):
        return (f"{__name__}.{self.__class__.__name__}", [self.model_name], {})
