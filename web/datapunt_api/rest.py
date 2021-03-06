from collections import OrderedDict

import json
import django_filters

from rest_framework import pagination, response
from rest_framework import renderers, serializers
from rest_framework import viewsets, filters
from rest_framework.reverse import reverse
from rest_framework.utils.urls import replace_query_param

from rest_framework_extensions.mixins import DetailSerializerMixin

DEFAULT_RENDERERS = (renderers.JSONRenderer, renderers.BrowsableAPIRenderer)
FORMATS = [dict(format=r.format, type=r.media_type) for r in DEFAULT_RENDERERS]


def get_links(view_name, kwargs=None, request=None):
    result = OrderedDict([
        ('self', dict(
            href=reverse(view_name, kwargs=kwargs, request=request)
        ))
    ])

    return result


class DataSetSerializerMixin(object):
    def to_representation(self, obj):
        result = super(obj).to_representation(obj)
        result['dataset'] = self.dataset
        return result


class LinksField(serializers.HyperlinkedIdentityField):

    def to_representation(self, value):
        request = self.context.get('request')

        result = OrderedDict([
            (
                'self', dict(
                    href=self.get_url(value, self.view_name, request, None))
            ),
        ])

        return result


class HALSerializer(serializers.HyperlinkedModelSerializer):
    url_field_name = '_links'
    serializer_url_field = LinksField


class DatapuntPagination(pagination.PageNumberPagination):
    page_size_query_param = 'page_size'

    def get_paginated_response(self, data):
        self_link = self.request.build_absolute_uri()
        if self_link.endswith(".api"):
            self_link = self_link[:-4]

        if self.page.has_next():
            next_link = replace_query_param(
                self_link, self.page_query_param, self.page.next_page_number())
        else:
            next_link = None

        if self.page.has_previous():
            prev_link = replace_query_param(
                self_link, self.page_query_param,
                self.page.previous_page_number())
        else:
            prev_link = None

        return response.Response(OrderedDict([
            ('_links', OrderedDict([
                ('self', dict(href=self_link)),
                ('next', dict(href=next_link)),
                ('previous', dict(href=prev_link)),
            ])),
            ('count', self.page.paginator.count),
            ('results', data)
        ]))


class DisabledHTMLFilterBackend(
        django_filters.rest_framework.DjangoFilterBackend):
    """
    See https://github.com/tomchristie/django-rest-framework/issues/3766
    This prevents DRF (Django Rest Framework)
    from generating the filter dropdowns which can be HUGE in our case
    """

    def to_html(self, _request, _queryset, _view):
        return ""


class DatapuntViewSet(DetailSerializerMixin, viewsets.ReadOnlyModelViewSet):
    renderer_classes = DEFAULT_RENDERERS
    pagination_class = DatapuntPagination
    # filter_backends = (DisabledHTMLFilterBackend,)


class RelatedSummaryField(serializers.Field):

    def to_representation(self, value):
        count = value.count()
        model_name = value.model.__name__
        mapping = model_name.lower() + "-list"
        url = reverse(mapping, request=self.context['request'])

        parent_pk = value.instance.pk
        filter_name = list(value.core_filters.keys())[0]

        return dict(
            count=count,
            href="{}?{}={}".format(url, filter_name, parent_pk),
        )


class DisplayField(serializers.Field):
    def __init__(self, *args, **kwargs):
        kwargs['source'] = '*'
        kwargs['read_only'] = True
        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        return str(value)


class MultipleGeometryField(serializers.Field):

    read_only = True

    def get_attribute(self, obj):
        # Checking if point geometry exists. If not returning the
        # regular multipoly geometry
        return obj.geometrie

    def to_representation(self, value):
        # Serilaize the GeoField. Value could be either None,
        # Point or MultiPoly
        res = ''
        if value:
            res = json.loads(value.geojson)
        return res
