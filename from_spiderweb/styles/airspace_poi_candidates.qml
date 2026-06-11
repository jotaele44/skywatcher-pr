<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<!-- QGIS style for airspace_poi_candidates.geojson (T7-61).
     Categorizes POI candidates by review_priority (HIGH/MEDIUM/LOW). -->
<qgis version="3.34" styleCategories="Symbology">
  <renderer-v2 type="categorizedSymbol" attr="review_priority" forceraster="0" enableorderby="0" symbollevels="0">
    <categories>
      <category render="true" value="HIGH" symbol="0" label="HIGH"/>
      <category render="true" value="MEDIUM" symbol="1" label="MEDIUM"/>
      <category render="true" value="LOW" symbol="2" label="LOW"/>
      <category render="true" value="" symbol="3" label="other"/>
    </categories>
    <symbols>
      <symbol type="marker" name="0" alpha="1" clip_to_extent="1">
        <layer class="SimpleMarker" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="214,40,40,255"/>
            <Option type="QString" name="name" value="circle"/>
            <Option type="QString" name="outline_color" value="35,35,35,255"/>
            <Option type="QString" name="size" value="4"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="marker" name="1" alpha="1" clip_to_extent="1">
        <layer class="SimpleMarker" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="247,127,0,255"/>
            <Option type="QString" name="name" value="circle"/>
            <Option type="QString" name="outline_color" value="35,35,35,255"/>
            <Option type="QString" name="size" value="3"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="marker" name="2" alpha="1" clip_to_extent="1">
        <layer class="SimpleMarker" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="252,191,73,255"/>
            <Option type="QString" name="name" value="circle"/>
            <Option type="QString" name="outline_color" value="35,35,35,255"/>
            <Option type="QString" name="size" value="2.5"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="marker" name="3" alpha="1" clip_to_extent="1">
        <layer class="SimpleMarker" enabled="1">
          <Option type="Map">
            <Option type="QString" name="color" value="150,150,150,255"/>
            <Option type="QString" name="name" value="circle"/>
            <Option type="QString" name="outline_color" value="35,35,35,255"/>
            <Option type="QString" name="size" value="2"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <blendMode>0</blendMode>
</qgis>
