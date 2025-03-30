from django.db import models


class Variable(models.Model):

    class Distribution(models.TextChoices):
        Normal = "Normal"
        Uniform = "Uniform"

    v_id: models.IntegerField[int, int] = models.IntegerField(primary_key=True)
    name: models.TextField[str, str] = models.TextField(null=True)
    distribution: models.CharField[Distribution, Distribution] = models.CharField(
        choices=Distribution, null=True, max_length=100
    )
    mean: models.FloatField[float, float] = models.FloatField(db_default=0.0)
    sigma: models.FloatField[float, float] = models.FloatField(db_default=1.0)
    lower: models.FloatField[float, float] = models.FloatField(db_default=0.0)
    upper: models.FloatField[float, float] = models.FloatField(db_default=1.0)
