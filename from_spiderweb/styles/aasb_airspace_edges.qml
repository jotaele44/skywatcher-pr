<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<!-- QGIS style for aasb_airspace_edges.csv (T7-61).
     Load the CSV as delimited-text geometry from from_lat/from_lon →
     to_lat/to_lon, then apply this graduated line style on `weight`. -->
<qgis version="3.34" styleCategories="Symbology">
  <renderer-v2 type="graduatedSymbol" attr="weight" graduatedMethod="GraduatedColor">
    <ranges>
      <range render="true" lower="0.000000" upper="2.000000" symbol="0" label="1 - 2 flights"/>
      <range render="true" lower="2.000000" upper="5.000000" symbol="1" label="3 - 5 flights"/>
      <range render="true" lower="5.000000" upper="1000000.000000" symbol="2" label="6+ flights"/>
    </ranges>
    <symbols>
      <symbol type="line" name="0" alpha="1" clip_to_extent="1">
        <layer class="SimpleLine" enabled="1">
          <Option type="Map">
            <Option type="QString" name="line_color" value="173,216,230,255"/>
            <Option type="QString" name="line_width" value="0.4"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="line" name="1" alpha="1" clip_to_extent="1">
        <layer class="SimpleLine" enabled="1">
          <Option type="Map">
            <Option type="QString" name="line_color" value="65,105,225,255"/>
            <Option type="QString" name="line_width" value="0.8"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="line" name="2" alpha="1" clip_to_extent="1">
        <layer class="SimpleLine" enabled="1">
          <Option type="Map">
            <Option type="QString" name="line_color" value="25,25,112,255"/>
            <Option type="QString" name="line_width" value="1.3"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <blendMode>0</blendMode>
</qgis>
