/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("pbc_1829587840")

  // add field
  collection.fields.addAt(8, new Field({
    "hidden": false,
    "id": "bool3275326989",
    "name": "expiry_notifird",
    "presentable": false,
    "required": false,
    "system": false,
    "type": "bool"
  }))

  return app.save(collection)
}, (app) => {
  const collection = app.findCollectionByNameOrId("pbc_1829587840")

  // remove field
  collection.fields.removeById("bool3275326989")

  return app.save(collection)
})
