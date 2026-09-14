from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Gets an item from a dictionary by key."""
    if dictionary is None:
        return 0
    return dictionary.get(key, 0)