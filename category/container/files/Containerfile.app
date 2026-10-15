# Rendered by cMeta from the container template "{{cmeta.template_alias}}" on the base "{{cmeta.base_alias}}"
#   cx container render {{cmeta.template_alias}} --distro={{cmeta.base}} [--template.<key>=<value>]
FROM {{cmeta.base_image}}
{{cmeta.clone_block}}
{{cmeta.app_block}}
{{cmeta.expose_block}}
CMD {{cmeta.cmd_json}}
