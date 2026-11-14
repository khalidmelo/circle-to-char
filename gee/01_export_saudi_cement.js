// Circle to Char — step 1: Saudi cement plants (char outlets for the siting model)
// Source: Spatial Finance Initiative, Global Database of Cement Production Assets
// (2021 snapshot, CC BY 4.0), via the awesome-gee-community-catalog.
// How to use: paste into https://code.earthengine.google.com, press Run.
// Then in the Console, click the small "pop-out" arrow on the chart below and press
// "Download CSV". Save it as  data/cement/saudi_cement.csv  in the project folder.

var cement = ee.FeatureCollection('projects/sat-io/open-datasets/SFI/global_cement_database_20210701');
var saudi = cement.filter(ee.Filter.eq('country', 'Saudi Arabia'));

saudi = saudi.map(function (f) {
  var c = f.geometry().coordinates();
  return f.set({lon: c.get(0), lat: c.get(1)});
});

print('Saudi cement plants:', saudi.size());

// A table chart gives a one-click CSV download from the Console.
var cols = ['uid', 'owner_name', 'city', 'state', 'plant_type', 'cap', 'status', 'year', 'lat', 'lon', 'accuracy'];
print(ui.Chart.feature.byFeature(saudi.select(cols), 'uid', cols.slice(1))
  .setChartType('Table'));

Map.centerObject(saudi, 5);
Map.addLayer(saudi, {color: 'red'}, 'Cement plants');
