from composeui.items.table.tableview import TableView

from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.model.djangoormmodel import DjangoORMModel

from typing import List, Optional
from django.db import models

from django.contrib import admin


class Variable(models.Model):

    class Meta:
        app_label = "variables"

    class Distribution(models.TextChoices):
        Normal = "Normal"
        Uniform = "Uniform"

    v_id = models.IntegerField(primary_key=True)
    name = models.TextField(null=True)
    distribution = models.CharField(choices=Distribution, null=True, max_length=100)
    mean = models.FloatField(default=0.0)
    sigma = models.FloatField(default=1.0)
    lower = models.FloatField(default=0.0)
    upper = models.FloatField(default=1.0)


admin.site.register(Variable)


class VariablesItems(AbstractTableItems[DjangoORMModel]):
    def __init__(self, model: DjangoORMModel) -> None:
        super().__init__(TableView(), model, title="Variables")
        self._titles = ["Name", "Distribution", "Id"]

    def get_nb_columns(self) -> int:
        return len(self._titles)

    def get_column_title(self, column: int) -> str:
        return self._titles[column]

    def get_nb_rows(self) -> int:
        return int(Variable.objects.count())

    def insert(self, row: int) -> Optional[int]:
        variable = Variable(name="Variable", distribution=Variable.Distribution.Normal)
        variable.save()
        return super().insert(row)

    def remove(self, row: int) -> Optional[int]:
        variable = Variable.objects.order_by("v_id")[row]
        variable.delete()
        return super().remove(row)

    def get_data(self, row: int, column: int) -> str:
        variable = Variable.objects.order_by("v_id")[row]
        if column == 0:
            return str(variable.name)
        elif column == 1:
            return str(variable.distribution)
        elif column == 2:
            return str(variable.v_id)
        return super().get_data(row, column)

    def get_data_by_row(self, row: int) -> List[str]:
        variable = Variable.objects.order_by("v_id")[row]
        return [
            variable.name,
            str(variable.distribution),
            str(variable.v_id),
        ]

    def get_all_datas(self) -> List[List[str]]:
        variables = Variable.objects.order_by("v_id")
        return [
            [
                variable.name,
                str(variable.distribution),
                str(variable.v_id),
            ]
            for variable in variables
        ]

    def set_data(self, row: int, column: int, value: str) -> bool:
        variable = Variable.objects.order_by("v_id")[row]
        if column == 0:
            variable.name = value
        elif column == 1:
            variable.distribution = Variable.Distribution(value)
        else:
            return False
        variable.save()
        return True
