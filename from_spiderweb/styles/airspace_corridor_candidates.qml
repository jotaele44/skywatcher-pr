<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<!-- QGIS style for airspace_corridor_candidates.geojson (T7-61).
     Categorizes corridors by corridor_label (HIGH/MEDIUM/LOW activity). -->
<qgis version="3.34" styleCategories="Symbology">
  <renderer-v2 type="categorizedSymbol" attr="corridor_label" forceraster="0" enableorderby="0" symbollevels="0">
    <categories>
      <category render="true" value="HIGH" symbol="0" label="HIGH activity"/>
      <category render="true" value="MEDIUM" symbol="1" label="MEDIUM activity"/>
      <category render="true" value="LOW" symbol="2" label="LOW activity"/>
    </categories>
    <symbols>
      <symbol type="line" name="0" alpha="1" clip_to_extent="1">
        <layer class="SimpleLine" enabled="1">
          <Option type="Map">
            <Option type="QString" name="line_color" value="214,40,40,255"/>
            <Option type="QString" name="line_width" value="1.2"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="line" name="1" alpha="1" clip_to_extent="1">
        <layer class="SimpleLine" enabled="1">
          <Option type="Map">
            <Option type="QString" name="line_color" value="247,127,0,255"/>
            <Option type="QString" name="line_width" value="0.8"/>
          </Option>
        </layer>
      </symbol>
      <symbol type="line" name="2" alpha="1" clip_to_extent="1">
        <layer class="SimpleLine" enabled="1">
          <Option type="Map">
            <Option type="QString" name="line_color" value="252,191,73,255"/>
            <Option type="QString" name="line_width" value="0.5"/>
          </Option>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
  <blendMode>0</blendMode>
</qgis>
