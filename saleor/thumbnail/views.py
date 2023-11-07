from collections import namedtuple
from typing import Optional

from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponseNotFound, HttpResponseRedirect, \
    HttpResponsePermanentRedirect
from graphql.error import GraphQLError

from ..account.models import User
from ..app.models import App, AppInstallation
from ..core.utils.events import call_event
from ..graphql.core.utils import from_global_id_or_error
from ..plugins.manager import get_plugins_manager
from ..product.models import Category, Collection, ProductMedia
from ..thumbnail.models import Thumbnail
from . import ALLOWED_ICON_THUMBNAIL_FORMATS, ALLOWED_THUMBNAIL_FORMATS
from .utils import (
    ProcessedIconImage,
    ProcessedImage,
    get_thumbnail_size,
    prepare_thumbnail_file_name, get_image_mimetype,
)

ModelData = namedtuple("ModelData", ["model", "image_field", "thumbnail_field"])

ICON_TYPE_TO_MODEL_DATA_MAPPING = {
    "App": ModelData(App, "brand_logo_default", "app"),
    "AppInstallation": ModelData(
        AppInstallation, "brand_logo_default", "app_installation"
    ),
}
TYPE_TO_MODEL_DATA_MAPPING = {
    "User": ModelData(User, "avatar", "user"),
    "Category": ModelData(Category, "background_image", "category"),
    "Collection": ModelData(Collection, "background_image", "collection"),
    "ProductMedia": ModelData(ProductMedia, "image", "product_media"),
    **ICON_TYPE_TO_MODEL_DATA_MAPPING,
}
UUID_IDENTIFIABLE_TYPES = ["User", "App", "AppInstallation"]


def handle_thumbnail(
    request, instance_id: str, size: str, format: Optional[str] = None
):
    """Create and return thumbnail for given instance in provided size and format.

    If the provided size is not in the available resolution list, the thumbnail with
    the closest available size is created and returned, if it does not exist.
    """
    # try to find corresponding instance based on given instance_id
    try:
        object_type, pk = from_global_id_or_error(instance_id, raise_error=True)
    except GraphQLError:
        return HttpResponseNotFound("Cannot found instance with the given id.")

    if object_type not in TYPE_TO_MODEL_DATA_MAPPING.keys():
        return HttpResponseNotFound("Invalid instance type.")

    # check formats
    format = format.lower() if format else None
    if object_type in ICON_TYPE_TO_MODEL_DATA_MAPPING:
        if format and format not in ALLOWED_ICON_THUMBNAIL_FORMATS:
            return HttpResponseNotFound("Unsupported icon image format.")
    elif format and format not in ALLOWED_THUMBNAIL_FORMATS:
        return HttpResponseNotFound("Unsupported image format.")

    try:
        size_px = get_thumbnail_size(int(size))
    except ValueError:
        return HttpResponseNotFound("Invalid size.")

    # return the thumbnail if it's already exist
    model_data = TYPE_TO_MODEL_DATA_MAPPING[object_type]
    if object_type in UUID_IDENTIFIABLE_TYPES:
        instance_id_lookup = model_data.thumbnail_field + "__uuid"
    else:
        instance_id_lookup = model_data.thumbnail_field + "_id"

    if thumbnail := Thumbnail.objects.filter(
        format=format, size=size_px, **{instance_id_lookup: pk}
    ).first():
        return HttpResponseRedirect(thumbnail.image.url)

    try:
        if object_type in UUID_IDENTIFIABLE_TYPES:
            instance = model_data.model.objects.get(uuid=pk)
        else:
            instance = model_data.model.objects.get(id=pk)
    except ObjectDoesNotExist:
        return HttpResponseNotFound("Instance with the given id cannot be found.")

    image = getattr(instance, model_data.image_field)
    if not bool(image):
        return HttpResponseNotFound("There is no image for provided instance.")

    # prepare thumbnail
    if object_type in ICON_TYPE_TO_MODEL_DATA_MAPPING:
        processed_image: ProcessedImage = ProcessedIconImage(
            image.name, size_px, format
        )
    else:
        processed_image = ProcessedImage(image.name, size_px, format)
    thumbnail_file, _ = processed_image.create_thumbnail()

    thumbnail_file_name = prepare_thumbnail_file_name(image.name, size_px, format)

    # save image thumbnail
    thumbnail = Thumbnail(
        size=size_px, format=format, **{model_data.thumbnail_field: instance}
    )
    thumbnail.image.save(thumbnail_file_name, thumbnail_file)
    thumbnail.save()

    # set additional `instance` attribute, to easily get instance data
    # for ThumbnailCreated subscription type
    setattr(thumbnail, "instance", instance)
    manager = get_plugins_manager()
    call_event(manager.thumbnail_created, thumbnail)
    content_type = get_image_mimetype(thumbnail.image)
    return HttpResponsePermanentRedirect(thumbnail.image.url, content_type=content_type)
