from __future__ import unicode_literals

from django.core.exceptions import PermissionDenied
try:
    from django.conf.urls import patterns, url
except ImportError:
    from django.conf.urls.defaults import patterns, url
from django.contrib import admin
from django.contrib.admin import helpers
from django.contrib.contenttypes.models import ContentType
from django.core.urlresolvers import reverse
from django.shortcuts import get_object_or_404, render
from django.contrib.admin.util import unquote
from django.utils.text import capfirst
from django.utils.html import mark_safe
from django.utils.translation import ugettext as _
try:
    from django.utils.encoding import force_text
except ImportError:  # django 1.3 compatibility
    from django.utils.encoding import force_unicode as force_text


class SimpleHistoryAdmin(admin.ModelAdmin):
    object_history_template = "simple_history/object_history.html"
    object_history_form_template = "simple_history/object_history_form.html"

    def get_urls(self):
        """Returns the additional urls used by the Reversion admin."""
        urls = super(SimpleHistoryAdmin, self).get_urls()
        admin_site = self.admin_site
        opts = self.model._meta
        try:
            info = opts.app_label, opts.module_name
        except AttributeError:
            info = opts.app_label, opts.model_name
        history_urls = patterns(
            "",
            url("^([^/]+)/history/([^/]+)/$",
                admin_site.admin_view(self.history_form_view),
                name='%s_%s_simple_history' % info),
        )
        return history_urls + urls

    def history_view(self, request, object_id, extra_context=None):
        "The 'history' admin view for this model."
        model = self.model
        opts = model._meta
        app_label = opts.app_label
        pk_name = opts.pk.attname
        history = getattr(model, model._meta.simple_history_manager_attribute)
        object_id = unquote(object_id)
        action_list = history.filter(**{pk_name: object_id})
        # If no history was found, see whether this object even exists.
        obj = get_object_or_404(model, pk=object_id)
        context = {
            'title': _('Change history: %s') % force_text(obj),
            'action_list': action_list,
            'module_name': capfirst(force_text(opts.verbose_name_plural)),
            'object': obj,
            'root_path': getattr(self.admin_site, 'root_path', None),
            'app_label': app_label,
            'opts': opts,
        }
        context.update(extra_context or {})
        return render(request, template_name=self.object_history_template,
                      dictionary=context, current_app=self.admin_site.name)

    def history_form_view(self, request, object_id, version_id):
        original_model = self.model
        original_opts = original_model._meta
        history = getattr(self.model,
                          self.model._meta.simple_history_manager_attribute)
        model = history.model
        opts = model._meta
        pk_name = original_opts.pk.attname
        record = get_object_or_404(model, **{
            pk_name: object_id,
            'history_id': version_id,
        })
        obj = record.instance
        obj._state.adding = False

        if not self.has_change_permission(request, obj):
            raise PermissionDenied

        formsets = []
        form_class = self.get_form(request, obj)
        if request.method == 'POST':
            form = form_class(request.POST, request.FILES, instance=obj)
            if form.is_valid():
                form_validated = True
                new_object = self.save_form(request, form, change=True)
            else:
                form_validated = False
                new_object = obj

            if form_validated:
                self.save_model(request, new_object, form, change=True)
                form.save_m2m()

                change_message = self.construct_change_message(request, form,
                                                               formsets)
                self.log_change(request, new_object, change_message)
                return self.response_change(request, new_object)

        else:
            form = form_class(instance=obj)

        admin_form = helpers.AdminForm(
            form,
            self.get_fieldsets(request, obj),
            self.prepopulated_fields,
            self.get_readonly_fields(request, obj),
            model_admin=self,
        )
        media = self.media + admin_form.media

        try:
            model_name = original_opts.module_name
        except AttributeError:
            model_name = original_opts.model_name
        url_triplet = self.admin_site.name, original_opts.app_label, model_name
        content_type_id = ContentType.objects.get_for_model(self.model).id
        context = {
            'title': _('Revert %s') % force_text(obj),
            'adminform': admin_form,
            'object_id': object_id,
            'original': obj,
            'is_popup': False,
            'media': mark_safe(media),
            'errors': helpers.AdminErrorList(form, formsets),
            'app_label': opts.app_label,
            'original_opts': original_opts,
            'changelist_url': reverse('%s:%s_%s_changelist' % url_triplet),
            'change_url': reverse('%s:%s_%s_change' % url_triplet,
                                  args=(obj.pk,)),
            'history_url': reverse('%s:%s_%s_history' % url_triplet,
                                   args=(obj.pk,)),
            # Context variables copied from render_change_form
            'add': False,
            'change': True,
            'has_add_permission': self.has_add_permission(request),
            'has_change_permission': self.has_change_permission(request, obj),
            'has_delete_permission': self.has_delete_permission(request, obj),
            'has_file_field': True,
            'has_absolute_url': False,
            'form_url': '',
            'opts': opts,
            'content_type_id': content_type_id,
            'save_as': self.save_as,
            'save_on_top': self.save_on_top,
            'root_path': getattr(self.admin_site, 'root_path', None),
        }
        return render(request, template_name=self.object_history_form_template,
                      dictionary=context, current_app=self.admin_site.name)

    def save_model(self, request, obj, form, change):
        """Set special model attribute to user for reference after save"""
        obj._history_user = request.user
        super(SimpleHistoryAdmin, self).save_model(request, obj, form, change)
