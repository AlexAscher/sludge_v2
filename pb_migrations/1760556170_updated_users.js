/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("pbc_1829587840")

  // remove field
  collection.fields.removeById("text3423285350")

  // add field
  collection.fields.addAt(4, new Field({
    "hidden": false,
    "id": "number2809058197",
    "max": null,
    "min": null,
    "name": "user_id",
    "onlyInt": false,
    "presentable": false,
    "required": false,
    "system": false,
    "type": "number"
  }))

  return app.save(collection)
}, (app) => {
  const collection = app.findCollectionByNameOrId("pbc_1829587840")

  // add field
  collection.fields.addAt(4, new Field({
    "autogeneratePattern": "",
    "hidden": false,
    "id": "text3423285350",
    "max": 0,
    "min": 0,
    "name": "telegram_id",
    "pattern": "",
    "presentable": false,
    "primaryKey": false,
    "required": false,
    "system": false,
    "type": "text"
  }))

  // remove field
  collection.fields.removeById("number2809058197")

  return app.save(collection)
})
