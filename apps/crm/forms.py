from apps.core.forms import StyledModelForm

from .models import LeadSource, LeadStage, RefusalReason


class LeadSourceForm(StyledModelForm):
    class Meta:
        model = LeadSource
        fields = ["name", "sort_order"]


class LeadStageForm(StyledModelForm):
    class Meta:
        model = LeadStage
        fields = ["name", "color", "sort_order"]

    def save(self, commit=True):
        if self.instance.pk is None:
            self.instance.kind = LeadStage.Kind.CUSTOM
        return super().save(commit)


class RefusalReasonForm(StyledModelForm):
    class Meta:
        model = RefusalReason
        fields = ["name", "sort_order"]
