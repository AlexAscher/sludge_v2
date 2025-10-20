/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("pbc_1829587840")

  // add field
  collection.fields.addAt(7, new Field({
    "hidden": false,
    "id": "number850033989",
    "max": null,
    "min": null,
    "name": "premium_until",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  return app.save(collection)
}, (app) => {
  const collection = app.findCollectionByNameOrId("pbc_1829587840")

  // remove field
  collection.fields.removeById("number850033989")

  return app.save(collection)
})
