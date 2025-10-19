/// <reference path="../pb_data/types.d.ts" />
migrate((app) => {
  const collection = app.findCollectionByNameOrId("pbc_1829587840")

  // update collection data
  unmarshal({
    "name": "users"
  }, collection)

  return app.save(collection)
}, (app) => {
  const collection = app.findCollectionByNameOrId("pbc_1829587840")

  // update collection data
  unmarshal({
    "name": "users1"
  }, collection)

  return app.save(collection)
})
