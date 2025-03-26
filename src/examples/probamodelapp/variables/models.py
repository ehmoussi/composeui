# type: ignore  # noqa: PGH003
from django.db import models


class Variable(models.Model):

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
