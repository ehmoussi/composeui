from django.db import models


class Variable(models.Model):

    class Distribution(models.TextChoices):
        Normal = "Normal"
        Uniform = "Uniform"

    v_id = models.IntegerField(primary_key=True)
    v_index = models.IntegerField(db_default=0)
    name = models.TextField(null=True)
    distribution = models.CharField(choices=Distribution, null=True, max_length=100)
    mean = models.FloatField(db_default=0.0)
    sigma = models.FloatField(db_default=1.0)
    lower = models.FloatField(db_default=0.0)
    upper = models.FloatField(db_default=1.0)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="variables_check_distribution",
                condition=models.Q(distribution__in=["Normal", "Uniform"]),
            )
        ]
