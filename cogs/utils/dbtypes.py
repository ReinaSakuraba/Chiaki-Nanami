"""Some random helper type things"""
import asyncqlio
import datetime


class JSON(asyncqlio.ColumnType):
    """Helper type because asyncqlio doesn't support JSONs at the moment."""
    def sql(self):
        return 'JSONB'


class Interval(asyncqlio.ColumnType):
    def sql(self):
        return 'INTERVAL'

    def validate_set(self, row, value):
        return isinstance(value, datetime.timedelta)
