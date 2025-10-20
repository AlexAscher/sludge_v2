/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("pbc_1829587840")

  // add field
  collection.fields.addAt(8, new Field({
    "hidden": false,
    "id": "date1924338900",
    "max": "",
    "min": "",
    "name": "premium_end",
    "presentable": false,
    "required": false,
    "system": false,
    "type": "date"
  }))

  return app.save(collection)
}, (app) => {
  const collection = app.findCollectionByNameOrId("pbc_1829587840")

  // remove field
  collection.fields.removeById("date1924338900")

  return app.save(collection)
})
