# MHWs EFX Attribute Type Reference

Mechanically generated reference of every `EFXAttribute` subclass known to [RE-Engine-Lib](https://github.com/kagenocookie/RE-Engine-Lib) for `EfxVersion.MHWilds`, plus the nested struct/enum types those attributes reference.

**How this was generated**: `ReeLib.Efx.EfxTools.GenerateEFXStructsJson(EfxVersion.MHWilds, ...)` reflects over the compiled attribute classes (the same code path RE-Engine-Lib uses to build its own EFX struct cache) and dumps every field's declared name, RSZ field type, array/fixed-length info, and any referenced enum/struct type. Nothing here was hand-transcribed from the `.cs` source, so field lists are exactly what the current vendored commit (see `PLAN.md`) will read/write for MHWs.

**What "Notes" does *not* mean**: field *names* come straight from the C# source and are sometimes self-explanatory (`LocalPosition`, `Color`) and sometimes not (`unk1`, `null2_23`). This document only records name + type + structural flags (array length, bitset, string-hash, etc.) — it does **not** attempt to explain what a field *does* in-game. RE-Engine-Lib's own field-level doc comments are essentially nonexistent for EFX attributes, and per `PLAN.md` that semantic knowledge is a separate, still-open effort (see the sister [EFX-Editor](https://github.com/Dimcirui/MHW-EFX-Editor) project's field-semantics work). Treat unexplained names as unknown, not as "obviously X".

238 attribute types, 38 nested struct/object types, 36 enums.

## Contents

- [Misc attributes](#misc-attributes) (45) — `EfxMiscStructs.cs`
- [Ribbon attributes](#ribbon-attributes) (31) — `EfxTypeRibbon.cs`
- [Transform attributes](#transform-attributes) (21) — `EfxTransform.cs`
- [Basic / lifecycle attributes](#basic--lifecycle-attributes) (19) — `EfxBasics.cs`
- [Velocity attributes](#velocity-attributes) (18) — `EfxVelocity.cs`
- [Particle (Pt) behavior attributes](#particle-pt-behavior-attributes) (17) — `EfxPtBehavior.cs`
- [Emitter attributes](#emitter-attributes) (14) — `EfxEmitter.cs`
- [Billboard attributes](#billboard-attributes) (11) — `EfxTypeBillboard.cs`
- [Mesh attributes](#mesh-attributes) (9) — `EfxTypeMesh.cs`
- [Polygon attributes](#polygon-attributes) (9) — `EfxTypePolygon.cs`
- [Vortexel (wind/heat) attributes](#vortexel-windheat-attributes) (9) — `EfxVortexel.cs`
- [Lightning attributes](#lightning-attributes) (8) — `EfxTypeLightning.cs`
- [Fade attributes](#fade-attributes) (7) — `EfxFade.cs`
- [Fluid attributes](#fluid-attributes) (6) — `EfxFluid.cs`
- [Strain ribbon attributes](#strain-ribbon-attributes) (5) — `EfxTypeStrain.cs`
- [Field attributes](#field-attributes) (5) — `EfxFieldTypes.cs`
- [General struct attributes](#general-struct-attributes) (4) — `EfxTypeGeneralStructs.cs`
- [Nested / common structs](#nested--common-structs) (38)
- [Enums](#enums) (36)

## Misc attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxMiscStructs.cs`_

<a id="attr-fixrandomgenerator"></a>
### `FixRandomGenerator` — TypeID 1

`ReeLib.Efx.Structs.Misc.EFXAttributeFixRandomGenerator`

| Field | Type | Notes |
|---|---|---|
| `useRandomSeedTableCount` | S32 |  |
| `randomSeedTable0` | S32 |  |
| `randomSeedTable1` | S32 |  |
| `randomSeedTable2` | S32 |  |
| `randomSeedTable3` | S32 |  |
| `randomSeedTable4` | S32 |  |
| `randomSeedTable5` | S32 |  |
| `randomSeedTable6` | S32 |  |
| `randomSeedTable7` | S32 |  |
| `tableSelectionGroup` | S32 |  |

<a id="attr-effectshader"></a>
### `EffectShader` — TypeID 3

`ReeLib.Efx.Structs.Misc.EFXAttributeEffectOptimizeShader`

| Field | Type | Notes |
|---|---|---|
| `unknShaderCRCHash0` | U32 |  |
| `unknShaderCRCHash1` | U32 |  |
| `unknShaderCRCHash2` | U32 |  |
| `unknShaderCRCHash3` | U32 |  |
| `unknShaderCRCHash4` | U32 |  |
| `unknShaderCRCHash5` | U32 |  |
| `unkn3` | ukn_type |  |
| `unknShaderCRCHash6` | U32 |  |
| `unknShaderCRCHash7` | U32 |  |
| `unknShaderCRCHash8` | U32 |  |
| `unknShaderCRCHash9` | U32 |  |
| `unknShaderCRCHash10` | U32 |  |
| `unknShaderCRCHash11` | U32 |  |
| `unkn10` | ukn_type |  |
| `unknShaderCRCHash12` | U32 |  |
| `unknShaderCRCHash13` | U32 |  |
| `unknShaderCRCHash14` | U32 |  |
| `unknShaderCRCHash15` | U32 |  |
| `unknShaderCRCHash16` | U32 |  |
| `unknShaderCRCHash17` | U32 |  |
| `unkn18` | ukn_type |  |
| `unknShaderCRCHash18` | U32 |  |
| `unknShaderCRCHash19` | U32 |  |
| `unknShaderCRCHash20` | U32 |  |
| `unknShaderCRCHash21` | U32 |  |
| `unkn20` | [`ByteSet`](#struct-byteset) |  |
| `shaderPath` | String |  |

<a id="attr-layout"></a>
### `Layout` — TypeID 21

`ReeLib.Efx.Structs.Misc.EFXAttributeLayout`

| Field | Type | Notes |
|---|---|---|
| `flags1` | U32 |  |
| `flags2` | U32 |  |
| `Unkn3` | U32 |  |
| `layoutName` | String |  |
| `len_layoutDataFloats` | S32 | StructSize → `layoutDataFloats` |
| `layoutDataFloats` | U8[] |  |

<a id="attr-vanisharea3d"></a>
### `VanishArea3D` — TypeID 92

`ReeLib.Efx.Structs.Misc.EFXAttributeVanishArea3D`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `wilds_unkn0` | Vec3 |  |
| `AreaPosition` | Vec3 |  |
| `AreaScale` | Vec3 |  |
| `AreaAngle` | Vec3 |  |
| `VanishFrame` | Range |  |
| `JointName` | String |  |

<a id="attr-vanisharea3dexpression"></a>
### `VanishArea3DExpression` — TypeID 93

`ReeLib.Efx.Structs.Misc.EFXAttributeVanishArea3DExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `14` |
| `positionX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `positionY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `positionZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-contrasthighlighter"></a>
### `ContrastHighlighter` — TypeID 108

`ReeLib.Efx.Structs.Misc.EFXAttributeContrastHighlighter`

| Field | Type | Notes |
|---|---|---|
| `Threshold` | F32 |  |
| `PeakMultiplier` | F32 |  |
| `EdgeLimiter` | F32 |  |
| `LuminanceScale` | F32 |  |
| `HighlightColor` | U32 |  |
| `HighlightIntensity` | F32 |  |

<a id="attr-colorgrading"></a>
### `ColorGrading` — TypeID 109

`ReeLib.Efx.Structs.Misc.EFXAttributeColorGrading`

| Field | Type | Notes |
|---|---|---|
| `HighBrightnessColor` | Color |  |
| `LowBrightnessColor` | Color |  |
| `HighBrightnessIntensity` | F32 |  |
| `LowBrightnessIntensity` | F32 |  |
| `HighGradingBorder` | F32 |  |
| `LowGradingBorder` | F32 |  |

<a id="attr-blink"></a>
### `Blink` — TypeID 111

`ReeLib.Efx.Structs.Misc.EFXAttributeBlink`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `MinRate` | F32 |  |
| `MaxRate` | F32 |  |
| `LowFrequency` | Range |  |
| `LowFrequencyWidth` | Range |  |
| `HighFrequency` | Range |  |
| `HighFrequencyWidth` | Range |  |

<a id="attr-noise"></a>
### `Noise` — TypeID 112

`ReeLib.Efx.Structs.Misc.EFXAttributeNoise`

| Field | Type | Notes |
|---|---|---|
| `LowFrequency` | Range |  |
| `LowFrequencyWidth` | Range |  |
| `HighFrequency` | Range |  |
| `HighFrequencyWidth` | Range |  |

<a id="attr-noiseexpression"></a>
### `NoiseExpression` — TypeID 113

`ReeLib.Efx.Structs.Misc.EFXAttributeNoiseExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `8` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-texelchanneloperator"></a>
### `TexelChannelOperator` — TypeID 114

`ReeLib.Efx.Structs.Misc.EFXAttributeTexelChannelOperator`

| Field | Type | Notes |
|---|---|---|
| `HueShift` | F32 |  |
| `HueIntensity` | F32 |  |
| `ShadeColor` | Color |  |
| `ShadeAlphaBlendRate` | F32 |  |
| `Desaturate` | F32 |  |
| `AmbientColorIntensity` | F32 |  |
| `EmissiveRate` | F32 |  |
| `EmissivePower` | F32 |  |
| `Opacity` | F32 |  |
| `HueIntensityCurve` | F32 |  |
| `UseIntEnvelope` | U32 |  |
| `Appear` | RangeI |  |
| `Keep` | RangeI |  |
| `Vanish` | RangeI |  |

<a id="attr-texelchanneloperatorclip"></a>
### `TexelChannelOperatorClip` — TypeID 115

`ReeLib.Efx.Structs.Misc.EFXAttributeTexelChannelOperatorClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `2` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-distortion"></a>
### `Distortion` — TypeID 129

`ReeLib.Efx.Structs.Misc.EFXAttributeDistortion`

| Field | Type | Notes |
|---|---|---|
| `DistortionType` | S32 (enum [`DistortionType`](#enum-distortiontype)) |  |
| `Influence` | F32 |  |
| `SpecularPower` | F32 |  |
| `SpecularIntensity` | F32 |  |
| `SpecularColor` | Color |  |
| `AlphaBlend` | F32 |  |
| `FadeScreenEdge` | Bool |  |

<a id="attr-distortionexpression"></a>
### `DistortionExpression` — TypeID 130

`ReeLib.Efx.Structs.Misc.EFXAttributeDistortionExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `5` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-drawsubscene"></a>
### `DrawSubscene` — TypeID 133

`ReeLib.Efx.Structs.Misc.EFXAttributeDrawSubscene`

_(no fields)_

<a id="attr-fakedof"></a>
### `FakeDoF` — TypeID 148

`ReeLib.Efx.Structs.Misc.EFXAttributeFakeDoF`

| Field | Type | Notes |
|---|---|---|
| `NearDistance` | F32 |  |
| `MaxScale` | F32 |  |
| `MinAlpha` | F32 |  |
| `UsingMipLevel` | U32 |  |
| `VanishDistance` | F32 |  |

<a id="attr-luminancebleed"></a>
### `LuminanceBleed` — TypeID 149

`ReeLib.Efx.Structs.Misc.EFXAttributeLuminanceBleed`

| Field | Type | Notes |
|---|---|---|
| `BleedType` | S32 (enum [`LuminanceBleedType`](#enum-luminancebleedtype)) |  |
| `SamplingType` | S32 (enum [`LuminanceBleedSamplingType`](#enum-luminancebleedsamplingtype)) |  |
| `Bleed` | F32 |  |
| `Slide` | F32 |  |
| `ColorScaler` | F32 |  |
| `ColorBias` | F32 |  |
| `TexelScaler` | F32 |  |

<a id="attr-listener"></a>
### `Listener` — TypeID 182

`ReeLib.Efx.Structs.Misc.EFXAttributeListener`

| Field | Type | Notes |
|---|---|---|
| `Unkn1` | U32 |  |
| `Unkn2` | U32 |  |

<a id="attr-depthoperator"></a>
### `DepthOperator` — TypeID 192

`ReeLib.Efx.Structs.Misc.EFXAttributeDepthOperator`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | U32 |  |
| `unkn1` | F32 |  |
| `unkn2` | F32 |  |
| `unkn3` | F32 |  |
| `unkn4` | F32 |  |
| `unkn5` | ukn_type |  |
| `mhws_unkn1` | F32 |  |
| `unkn6` | F32 |  |
| `unkn7` | ukn_type |  |
| `unkn8` | F32 |  |
| `unkn9` | ukn_type |  |
| `radians10` | F32 |  |
| `mhws_unkn2` | ukn_type |  |
| `unkn11` | F32 |  |
| `unkn12` | ukn_type |  |

<a id="attr-planecollider"></a>
### `PlaneCollider` — TypeID 193

`ReeLib.Efx.Structs.Misc.EFXAttributePlaneCollider`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Position` | Vec3 |  |
| `Rotation` | Vec3 |  |
| `BounceNum` | RangeI |  |
| `BounceRate` | Range |  |
| `FaceNormalRotation` | Vec3 |  |
| `IdleTime` | RangeI |  |

<a id="attr-depthocclusion"></a>
### `DepthOcclusion` — TypeID 195

`ReeLib.Efx.Structs.Misc.EFXAttributeDepthOcclusion`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |

<a id="attr-windinfluence3ddelayframe"></a>
### `WindInfluence3DDelayFrame` — TypeID 198

`ReeLib.Efx.Structs.Misc.EFXAttributeWindInfluence3DDelayFrame`

| Field | Type | Notes |
|---|---|---|
| `frameDelay` | U32 |  |
| `unkn2` | U32 |  |

<a id="attr-windinfluence3d"></a>
### `WindInfluence3D` — TypeID 199

`ReeLib.Efx.Structs.Misc.EFXAttributeWindInfluence3D`

| Field | Type | Notes |
|---|---|---|
| `InfluenceRate` | Range |  |
| `InfluenceCoef` | Range |  |
| `InfluenceFrame` | RangeI |  |

<a id="attr-attractor"></a>
### `Attractor` — TypeID 200

`ReeLib.Efx.Structs.Misc.EFXAttributeAttractor`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `AttractPosition` | Vec3 |  |
| `ForceScale` | Range |  |
| `ReversalForceScale` | Range |  |
| `ReversalDistance` | Range |  |
| `ForceResist` | F32 |  |
| `unknWild1` | ukn_type |  |
| `unknWild2` | ukn_type |  |
| `unknWild3` | Range |  |
| `unknWild4` | Range |  |
| `unknWild5` | Range |  |
| `unknWild6` | Range |  |
| `unknWild7` | Range |  |
| `unknWild8` | Range |  |
| `unknWild9` | Range |  |
| `unknWild10` | ukn_type |  |
| `endwilds` | ukn_type |  |
| `boneName` | String |  |

<a id="attr-attractorclip"></a>
### `AttractorClip` — TypeID 201

`ReeLib.Efx.Structs.Misc.EFXAttributeAttractorClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `7` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-attractorexpression"></a>
### `AttractorExpression` — TypeID 202

`ReeLib.Efx.Structs.Misc.EFXAttributeAttractorExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `11` |
| `posX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posX_2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posY_2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posZ_2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `attractionForce` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11_Wilds` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-drawoverlay"></a>
### `DrawOverlay` — TypeID 216

`ReeLib.Efx.Structs.Misc.EFXAttributeDrawOverlay`

| Field | Type | Notes |
|---|---|---|
| `Segment` | U32 |  |
| `Priority` | U32 |  |
| `CameraID` | U32 |  |
| `UnknWilds` | ukn_type |  |

<a id="attr-ignoreplayercolor"></a>
### `IgnorePlayerColor` — TypeID 230

`ReeLib.Efx.Structs.Misc.EFXAttributeIgnorePlayerColor`

_(no fields)_

<a id="attr-ignoresettings"></a>
### `IgnoreSettings` — TypeID 231

`ReeLib.Efx.Structs.Misc.EFXAttributeIgnoreSettings`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |

<a id="attr-proceduraldistortiondelayframe"></a>
### `ProceduralDistortionDelayFrame` — TypeID 232

`ReeLib.Efx.Structs.Misc.EFXAttributeProceduralDistortionDelayFrame`

| Field | Type | Notes |
|---|---|---|
| `frameDelay` | U32 |  |
| `unkn` | ukn_type |  |

<a id="attr-proceduraldistortion"></a>
### `ProceduralDistortion` — TypeID 233

`ReeLib.Efx.Structs.Misc.EFXAttributeProceduralDistortion`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `UScale` | F32 |  |
| `VScale` | F32 |  |
| `WaveFrequency` | F32 |  |
| `WaveAmplitude` | F32 |  |
| `WaveAmplitudeCoef` | F32 |  |
| `WaveOffset` | F32 |  |
| `WaveTimer` | F32 |  |
| `SpinInit` | F32 |  |
| `SpinMax` | F32 |  |
| `SpinTimer` | F32 |  |
| `SpinTimerCoef` | F32 |  |
| `RadialOscillationFrequency` | F32 |  |
| `RadialOscillationAmplitude` | F32 |  |
| `RadialOscillationFrequencyNoiseFrequency` | F32 |  |
| `RadialOscillationFrequencyNoiseAmplitude` | F32 |  |
| `RadialOscillationAmplitudeNoiseFrequency` | F32 |  |
| `RadialOscillationAmplitudeNoiseAmplitude` | F32 |  |
| `RadialOscillationTimer` | F32 |  |

<a id="attr-proceduraldistortionclip"></a>
### `ProceduralDistortionClip` — TypeID 234

`ReeLib.Efx.Structs.Misc.EFXAttributeProceduralDistortionClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `7` |
| `unkn1` | ukn_type |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-proceduraldistortionexpression"></a>
### `ProceduralDistortionExpression` — TypeID 235

`ReeLib.Efx.Structs.Misc.EFXAttributeProceduralDistortionExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `18` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-stretchblur"></a>
### `StretchBlur` — TypeID 237

`ReeLib.Efx.Structs.Misc.EFXAttributeStretchBlur`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `TargetStencil` | U32 |  |
| `StrengthBlur` | F32 |  |
| `ScreenFadeRange` | Vec2 |  |
| `SamplingSize` | Vec2 |  |
| `AlphaIntensity` | F32 |  |
| `AdjustRotationBySpeed` | F32 |  |
| `SamplingOffset` | Vec3 |  |

<a id="attr-flowmap"></a>
### `FlowMap` — TypeID 241

`ReeLib.Efx.Structs.Misc.EFXAttributeFlowMap`

| Field | Type | Notes |
|---|---|---|
| `Strength` | Range |  |
| `StrengthCoef` | Range |  |
| `Speed` | Range |  |
| `SpeedCoef` | Range |  |
| `flowmapMaskPath` | String |  |

<a id="attr-rgbcommon"></a>
### `RgbCommon` — TypeID 242

`ReeLib.Efx.Structs.Misc.EFXAttributeRgbCommon`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `GreenChColor` | Color |  |
| `GreenChColorRange` | Color |  |
| `GreenChIntensity` | F32 |  |
| `GreenChSaturate` | F32 |  |
| `GreenChCurve` | F32 |  |
| `RedChColor` | Color |  |
| `RedChColorRange` | Color |  |
| `RedChIntensity` | F32 |  |
| `RedChAlphaToB` | F32 |  |
| `Alpha` | F32 |  |
| `UseGreenChLife` | Bool |  |
| `GreenChAppearFrame` | RangeI |  |
| `GreenChKeepFrame` | RangeI |  |
| `GreenChVanishFrame` | RangeI |  |
| `GreenChLighting` | Bool |  |
| `GreenChLifeType` | S32 (enum [`LifeType`](#enum-lifetype)) |  |
| `UseRedChLife` | U8 |  |
| `RedChAppearFrame` | RangeI |  |
| `RedChKeepFrame` | RangeI |  |
| `RedChVanishFrame` | RangeI |  |
| `RedChLighting` | Bool |  |
| `RedChLifeType` | S32 (enum [`LifeType`](#enum-lifetype)) |  |

<a id="attr-rgbcommonexpression"></a>
### `RgbCommonExpression` — TypeID 243

`ReeLib.Efx.Structs.Misc.EFXAttributeRgbCommonExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `22` |
| `particleColor` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorIntensityGreen` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorSaturate` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `particleColor2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorIntensityRed` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn20` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn21` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn22` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-rgbwater"></a>
### `RgbWater` — TypeID 244

`ReeLib.Efx.Structs.Misc.EFXAttributeRgbWater`

| Field | Type | Notes |
|---|---|---|
| `SpecularColor` | Color |  |
| `mhws_unkn` | F32 |  |
| `SpecularIntensity` | F32 |  |
| `SheetColor` | Color |  |
| `SheetIntensity` | F32 |  |
| `GtoB` | F32 |  |
| `Alpha` | F32 |  |
| `UseSpecularLife` | Bool |  |
| `SpecularAppearFrame` | RangeI |  |
| `SpecularKeepFrame` | RangeI |  |
| `SpecularVanishFrame` | RangeI |  |
| `SpecularLifeType` | S32 (enum [`LifeType`](#enum-lifetype)) |  |
| `UseSheetLife` | U8 |  |
| `SheetAppearFrame` | RangeI |  |
| `SheetKeepFrame` | RangeI |  |
| `SheetVanishFrame` | RangeI |  |
| `SheetLifeType` | S32 (enum [`LifeType`](#enum-lifetype)) |  |
| `UseGtoBLife` | U8 |  |
| `GtoBAppearFrame` | RangeI |  |
| `GtoBKeepFrame` | RangeI |  |
| `GtoBVanishFrame` | RangeI |  |
| `GtoBLifeType` | S32 (enum [`LifeType`](#enum-lifetype)) |  |

<a id="attr-rgbwaterexpression"></a>
### `RgbWaterExpression` — TypeID 245

`ReeLib.Efx.Structs.Misc.EFXAttributeRgbWaterExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `13` |
| `particleColor` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorIntensityGreen` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorSaturate` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `particleColor2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorIntensityRed` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn20` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn21` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn22` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn23` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn24` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn25` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn26` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn27` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-assigncsv"></a>
### `AssignCSV` — TypeID 247

`ReeLib.Efx.Structs.Misc.EFXAttributeAssignCSV`

| Field | Type | Notes |
|---|---|---|
| `RandomizeIndexOrder` | Bool |  |
| `UseTableRange` | Bool |  |
| `mTableRange` | RangeI |  |
| `efcsvPostionListPath` | String |  |
| `efcsvRotationListPath` | String |  |
| `efcsvVelocityListPath` | String |  |
| `efcsvColorListPath` | String |  |

<a id="attr-destinationcsv"></a>
### `DestinationCSV` — TypeID 248

`ReeLib.Efx.Structs.Misc.EFXAttributeDestinationCSV`

| Field | Type | Notes |
|---|---|---|
| `unkn1` | U32 |  |
| `unkn2` | ukn_type |  |
| `unkn3` | ukn_type |  |
| `unkn4` | U32 |  |
| `unkn5` | ukn_type |  |
| `unkn6` | ukn_type |  |
| `unkn7` | ukn_type |  |
| `efcsvPath` | String |  |
| `unknPath2` | String |  |
| `unknPath3` | String |  |
| `unknPath4` | String |  |

<a id="attr-terrainsnap"></a>
### `TerrainSnap` — TypeID 250

`ReeLib.Efx.Structs.Misc.EFXAttributeTerrainSnap`

| Field | Type | Notes |
|---|---|---|
| `SnapType` | S32 (enum [`TerrainSnapType`](#enum-terrainsnaptype)) |  |
| `InitSnap` | Bool |  |
| `HorizontalBounceRate` | Range |  |
| `VerticalBounceRate` | Range |  |
| `Offset` | Range |  |
| `IgnoreScale` | Bool |  |
| `FinishParticleAngleApplyEmitterAngle` | Bool |  |
| `FinishParticleAngleMaxRad` | F32 |  |
| `FinishParticleAngleMinRad` | F32 |  |
| `FinishParticleAngleFrame` | Range |  |
| `KillParticleHeight` | F32 |  |
| `uknByte` | U8 |  |

<a id="attr-repeatarea"></a>
### `RepeatArea` — TypeID 251

`ReeLib.Efx.Structs.Misc.EFXAttributeRepeatArea`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Area` | Vec3 |  |
| `Unkn` | F32 |  |

<a id="attr-emitmask"></a>
### `EmitMask` — TypeID 252

`ReeLib.Efx.Structs.Misc.EFXAttributeEmitMask`

| Field | Type | Notes |
|---|---|---|
| `mask` | U32 |  |

<a id="attr-trigger"></a>
### `Trigger` — TypeID 254

`ReeLib.Efx.Structs.Misc.EFXAttributeTrigger`

| Field | Type | Notes |
|---|---|---|
| `unkn1` | U32 |  |
| `unkn2` | ukn_type |  |
| `unkn3` | F32 |  |

## Ribbon attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxTypeRibbon.cs`_

<a id="attr-typeribbonfollow"></a>
### `TypeRibbonFollow` — TypeID 33

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonFollow`

| Field | Type | Notes |
|---|---|---|
| `BlendFlags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `Intensity` | F32 |  |
| `EdgeBlendRange` | F32 |  |
| `AlphaRate` | F32 |  |
| `Flags` | U32 |  |
| `SizeScalar` | Range |  |
| `Width` | Range |  |
| `TextureRepeatNum` | F32 |  |
| `ShadowMultiplier` | F32 |  |
| `FadeSide` | U32 |  |
| `FollowFlags` | U32 |  |
| `StretchDistance` | Vec2 |  |
| `Unkn` | U32 |  |
| `ShapeDivision` | U32 |  |
| `SplineDivision` | U32 |  |
| `HeadColor` | Color |  |
| `ColorPlace1` | Color |  |
| `ColorPlace2` | Color |  |
| `ColorPlace1Ratio` | F32 |  |
| `ColorPlace2Ratio` | F32 |  |
| `HeadScale` | F32 |  |
| `ScalePlace1` | F32 |  |
| `ScalePlace2` | F32 |  |
| `ScalePlace1Ratio` | F32 |  |
| `ScalePlace2Ratio` | F32 |  |
| `FadeByTwistMin` | F32 |  |
| `FadeByTwistMax` | F32 |  |
| `GhostStretch` | Range |  |

<a id="attr-typeribbonlength"></a>
### `TypeRibbonLength` — TypeID 34

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonLength`

| Field | Type | Notes |
|---|---|---|
| `BlendFlags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `Intensity` | F32 |  |
| `EdgeBlendRange` | F32 |  |
| `AlphaRate` | F32 |  |
| `Flags` | U32 |  |
| `SizeScalar` | Range |  |
| `Width` | Range |  |
| `TextureRepeatNum` | F32 |  |
| `ShadowMultiplier` | F32 |  |
| `FadeSide` | F32 |  |
| `LengthFlags` | U32 |  |
| `Length` | Range |  |
| `ShapeDivision` | U32 |  |
| `BasingPoint` | Range |  |
| `ReleaseFixEnd` | Range |  |
| `DirectionX` | Range |  |
| `DirectionY` | Range |  |
| `DirectionZ` | Range |  |
| `HeadColor` | Color |  |
| `ColorPlace1` | Color |  |
| `ColorPlace2` | Color |  |
| `ColorPlace1Ratio` | F32 |  |
| `ColorPlace2Ratio` | F32 |  |
| `HeadScale` | F32 |  |
| `ScalePlace1` | F32 |  |
| `ScalePlace2` | F32 |  |
| `ScalePlace1Ratio` | F32 |  |
| `ScalePlace2Ratio` | F32 |  |
| `GhostStretch` | Range |  |

<a id="attr-typeribbonchain"></a>
### `TypeRibbonChain` — TypeID 35

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonChain`

| Field | Type | Notes |
|---|---|---|
| `unkn1` | U32 |  |
| `color1` | Color |  |
| `color2` | Color |  |
| `unkn2_0` | F32 |  |
| `unkn2_1` | F32 |  |
| `unkn2_2` | F32 |  |
| `unkn2_3` | F32 |  |
| `re4_unkn1_1` | U8 |  |
| `re4_unkn1_2` | U8 |  |
| `re4_unkn1_3` | U8 |  |
| `re4_unkn1_4` | U8 |  |
| `unkn2_4` | F32 |  |
| `unkn2_5` | F32 |  |
| `unkn2_6` | F32 |  |
| `unkn2_7` | F32 |  |
| `mhws_unkn1` | U32 |  |
| `unkn2_8` | F32 |  |
| `rert_unkn1` | F32 |  |
| `dd2_unkn0` | F32 |  |
| `unkn2_9_1` | [`ByteSet`](#struct-byteset) |  |
| `unkn2_10` | F32 |  |
| `unkn2_11` | F32 |  |
| `unkn2_12` | F32 |  |
| `unkn2_13` | F32 |  |
| `unkn2_14` | F32 |  |
| `unkn2_15` | F32 |  |
| `unkn2_16` | F32 |  |
| `unkn2_17` | F32 |  |
| `unkn2_19` | F32 |  |
| `unkn2_20` | F32 |  |
| `unkn2_21` | F32 |  |
| `rert_unkn0` | F32 |  |
| `unkn2_22` | F32 |  |
| `unkn2_23` | F32 |  |
| `re4_unkn2_hash` | U32 |  |
| `unkn2_24` | F32 |  |
| `unkn2_25` | F32 |  |
| `unkn2_26` | F32 |  |
| `unkn2_27` | F32 |  |
| `unkn2_28` | F32 |  |
| `unkn2_29` | F32 |  |
| `unkn2_30` | F32 |  |
| `unkn2_31` | F32 |  |
| `unkn2_32` | F32 |  |
| `unkn2_33` | Color |  |
| `unkn2_34` | Color |  |
| `unkn2_35` | Color |  |
| `unkn2_36` | F32 |  |
| `unkn2_37` | F32 |  |
| `unkn2_38` | F32 |  |
| `unkn2_39` | F32 |  |
| `unkn2_40` | F32 |  |
| `unkn2_41` | F32 |  |
| `unkn2_42` | F32 |  |
| `unkn2_43` | F32 |  |
| `unkn2_44` | F32 |  |
| `unkn2_45` | F32 |  |
| `unkn2_46` | F32 |  |
| `unkn2_47` | F32 |  |
| `unkn2_48` | F32 |  |
| `unkn2_49` | F32 |  |
| `dd2_unkn1` | F32 |  |
| `dd2_unkn2` | F32 |  |
| `dd2_unkn3` | F32 |  |
| `dd2_unkn4` | F32 |  |
| `dd2_unkn5` | F32 |  |
| `dd2_unkn6` | F32 |  |
| `dd2_unkn7` | F32 |  |
| `mhws_unkn2` | F32 |  |

<a id="attr-typeribbonfixend"></a>
### `TypeRibbonFixEnd` — TypeID 36

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonFixEnd`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `color0` | Color |  |
| `color1` | Color |  |
| `unkn2_0` | F32 |  |
| `unkn2_1` | F32 |  |
| `unkn2_2` | F32 |  |
| `unkn2_3` | F32 |  |
| `re4_unkn0` | U32 |  |
| `unkn2_4` | F32 |  |
| `unkn2_5` | F32 |  |
| `unkn2_6` | F32 |  |
| `unkn2_7` | F32 |  |
| `Flags2_Wilds` | U32 |  |
| `unkn2_8` | F32 |  |
| `sb_unkn0` | F32 |  |
| `dd2_unkn0` | F32 |  |
| `unkn2_9` | U32 |  |
| `unkn2_10` | F32 |  |
| `unkn2_11` | F32 |  |
| `unkn2_12` | U32 |  |
| `unkn2_13` | U32 |  |
| `unkn2_15` | F32 |  |
| `unkn2_16` | S32 |  |
| `unkn2_17` | S32 |  |
| `unkn2_18` | S32 |  |
| `unkn2_19` | F32 |  |
| `unkn2_20` | F32 |  |
| `unkn2_21` | F32 |  |
| `unkn2_22` | F32 |  |
| `unkn2_23` | F32 |  |
| `unkn2_24` | F32 |  |
| `unkn2_25` | F32 |  |
| `unkn2_26` | F32 |  |
| `unkn2_27` | F32 |  |

<a id="attr-typeribbonlightweight"></a>
### `TypeRibbonLightweight` — TypeID 37

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonLightweight`

| Field | Type | Notes |
|---|---|---|
| `unkn1` | U32 |  |
| `color0` | Color |  |
| `color1` | Color |  |
| `unkn2_0` | F32 |  |
| `unkn2_1` | U32 |  |
| `unkn2_2` | U32 |  |
| `unkn2_3` | F32 |  |
| `unkn2_4` | F32 |  |
| `unkn2_5` | F32 |  |
| `unkn2_6` | F32 |  |
| `sb_unkn0` | F32 |  |
| `unkn2_7` | F32 |  |
| `dd2_unkn` | F32 |  |
| `unkn2_8` | U32 |  |
| `unkn2_9` | F32 |  |
| `unkn2_10` | F32 |  |

<a id="attr-typeribbonparticle"></a>
### `TypeRibbonParticle` — TypeID 38

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonParticle`

| Field | Type | Notes |
|---|---|---|
| `ukn1` | U32 |  |
| `color1` | Color |  |
| `color2` | Color |  |
| `ukn5` | F32 |  |
| `ukn6` | U32 |  |
| `ukn7` | U32 |  |
| `ukn8` | F32 |  |
| `ukn9` | U32 |  |
| `ukn10` | F32 |  |
| `ukn11` | F32 |  |
| `ukn12` | F32 |  |
| `ukn14` | F32 |  |
| `ukn15` | F32 |  |
| `ukn16` | F32 |  |
| `ukn17` | F32 |  |
| `color3` | U32 |  |
| `color4` | U32 |  |
| `color5` | U32 |  |
| `ukn18` | U32 |  |
| `ukn19` | F32 |  |
| `ukn20` | F32 |  |
| `ukn21` | F32 |  |
| `ukn22` | Color |  |
| `ukn23` | Color |  |
| `ukn24` | Color |  |
| `ukn25` | F32 |  |
| `ukn26` | F32 |  |
| `ukn27` | F32 |  |
| `ukn28` | F32 |  |
| `ukn29` | F32 |  |
| `ukn30` | F32 |  |
| `ukn31` | F32 |  |
| `ukn32` | F32 |  |
| `ukn33` | F32 |  |

<a id="attr-typeribbonfollowmaterial"></a>
### `TypeRibbonFollowMaterial` — TypeID 39

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonFollowMaterial`

| Field | Type | Notes |
|---|---|---|
| `BlendFlags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `Intensity` | F32 |  |
| `EdgeBlendRange` | F32 |  |
| `AlphaRate` | F32 |  |
| `Flags` | U32 |  |
| `SizeScalar` | Range |  |
| `Width` | Range |  |
| `TextureRepeatNum` | F32 |  |
| `ShadowMultiplier` | F32 |  |
| `FadeSide` | F32 |  |
| `FollowFlags` | U32 |  |
| `StretchDistance` | Vec2 |  |
| `ShapeDivision` | U32 |  |
| `SplineDivision` | U32 |  |
| `Unkn1` | U32 |  |
| `HeadColor` | Color |  |
| `ColorPlace1` | Color |  |
| `ColorPlace2` | Color |  |
| `ColorPlace1Ratio` | F32 |  |
| `ColorPlace2Ratio` | F32 |  |
| `HeadScale` | F32 |  |
| `ScalePlace1` | F32 |  |
| `ScalePlace2` | F32 |  |
| `ScalePlace1Ratio` | F32 |  |
| `ScalePlace2Ratio` | F32 |  |
| `Unkn2` | F32 |  |
| `Unkn3` | F32 |  |
| `Unkn4` | F32 |  |
| `FadeByTwistMin` | F32 |  |
| `FadeByTwistFlags` | U32 |  |
| `material` | [`EfxMaterialStructBase`](#struct-efxmaterialstructbase) |  |

<a id="attr-typeribbonfollowmaterialclip"></a>
### `TypeRibbonFollowMaterialClip` — TypeID 40

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonFollowMaterialClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `10` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxMaterialClipData`](#struct-efxmaterialclipdata) |  |

<a id="attr-typeribbonfollowmaterialexpression"></a>
### `TypeRibbonFollowMaterialExpression` — TypeID 41

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonFollowMaterialExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `15` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `materialExpressionCount` | U32 |  |
| `materialExpressions` | [`EFXMaterialExpressionList`](#struct-efxmaterialexpressionlist) |  |

<a id="attr-typeribbonlengthmaterial"></a>
### `TypeRibbonLengthMaterial` — TypeID 42

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonLengthMaterial`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `color1` | Color |  |
| `color2` | Color |  |
| `unkn4` | F32 |  |
| `unkn5` | ukn_type |  |
| `unkn6` | ukn_type |  |
| `unkn7` | F32 |  |
| `unkn8` | U32 |  |
| `unkn9` | F32 |  |
| `unkn10` | F32 |  |
| `unkn11` | F32 |  |
| `unkn12` | F32 |  |
| `Flags2_Wilds` | U32 |  |
| `dd2_unkn2` | F32 |  |
| `wilds_unkn1` | F32 |  |
| `dd2_unkn3` | F32 |  |
| `unkn13` | U32 |  |
| `unkn14` | F32 |  |
| `unkn15` | F32 |  |
| `unkn17` | F32 |  |
| `unkn18` | F32 |  |
| `unkn19` | F32 |  |
| `unkn20` | ukn_type |  |
| `unkn21` | F32 |  |
| `unkn22` | F32 |  |
| `unkn23` | F32 |  |
| `unkn24` | F32 |  |
| `unkn25` | F32 |  |
| `unkn26` | F32 |  |
| `color3` | Color |  |
| `color4` | Color |  |
| `color5` | Color |  |
| `unkn30` | F32 |  |
| `unkn31` | F32 |  |
| `unkn32` | F32 |  |
| `unkn33` | F32 |  |
| `unkn34` | F32 |  |
| `unkn35` | F32 |  |
| `unkn36` | F32 |  |
| `unkn37` | F32 |  |
| `unkn38` | ukn_type |  |
| `unkn39` | U32 |  |
| `material` | [`EfxMaterialStructBase`](#struct-efxmaterialstructbase) |  |

<a id="attr-typeribbonlengthmaterialclip"></a>
### `TypeRibbonLengthMaterialClip` — TypeID 43

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonLengthMaterialClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `4` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxMaterialClipData`](#struct-efxmaterialclipdata) |  |

<a id="attr-typeribbonlengthmaterialexpression"></a>
### `TypeRibbonLengthMaterialExpression` — TypeID 44

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonLengthMaterialExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `15` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `materialExpressionCount` | S32 |  |
| `materialExpressions` | [`EFXMaterialExpressionList`](#struct-efxmaterialexpressionlist) |  |

<a id="attr-typeribbonchainmaterial"></a>
### `TypeRibbonChainMaterial` — TypeID 45

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonChainMaterial`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | U32 |  |
| `color1` | Color |  |
| `color2` | Color |  |
| `unkn3` | F32 |  |
| `unkn4` | ukn_type |  |
| `unkn5` | ukn_type |  |
| `unkn6` | ukn_type |  |
| `unkn7` | U32 |  |
| `unkn8` | F32 |  |
| `unkn9` | ukn_type |  |
| `unkn10` | F32 |  |
| `unkn11` | F32 |  |
| `unkn12` | F32 |  |
| `unkn13` | F32 |  |
| `unkn14` | F32 |  |
| `unkn15` | U32 |  |
| `unkn16` | F32 |  |
| `unkn17` | F32 |  |
| `unkn18` | F32 |  |
| `unkn19` | F32 |  |
| `unkn20` | F32 |  |
| `color3` | F32 |  |
| `color4` | F32 |  |
| `color5` | F32 |  |
| `unkn22` | U32 |  |
| `unkn23` | F32 |  |
| `unkn24` | F32 |  |
| `unkn25` | F32 |  |
| `unkn26` | ukn_type |  |
| `unkn27` | F32 |  |
| `unkn28` | ukn_type |  |
| `unkn29` | F32 |  |
| `unkn30` | ukn_type |  |
| `unkn31` | ukn_type |  |
| `unkn32` | ukn_type |  |
| `unkn33` | F32 |  |
| `unkn34` | ukn_type |  |
| `unkn35` | ukn_type |  |
| `unkn36` | ukn_type |  |
| `unkn37` | F32 |  |
| `unkn38` | ukn_type |  |
| `unkn39` | Color |  |
| `unkn40` | Color |  |
| `unkn41` | Color |  |
| `unkn42` | F32 |  |
| `unkn43` | F32 |  |
| `unkn44` | F32 |  |
| `unkn45` | F32 |  |
| `unkn46` | F32 |  |
| `unkn47` | F32 |  |
| `unkn48` | F32 |  |
| `unkn49` | F32 |  |
| `unkn50` | F32 |  |
| `unkn51` | F32 |  |
| `unkn52` | F32 |  |
| `unkn53` | F32 |  |
| `unkn54` | F32 |  |
| `unkn55` | F32 |  |
| `unkn56` | ukn_type |  |
| `unkn57` | ukn_type |  |
| `unkn58` | ukn_type |  |
| `unkn59` | ukn_type |  |
| `unkn60` | F32 |  |
| `unkn61` | ukn_type |  |
| `unkn62` | F32 |  |
| `unkn63` | U32 |  |
| `material` | [`EfxMaterialStructBase`](#struct-efxmaterialstructbase) |  |

<a id="attr-typeribbonchainmaterialclip"></a>
### `TypeRibbonChainMaterialClip` — TypeID 46

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonChainMaterialClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `6` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxMaterialClipData`](#struct-efxmaterialclipdata) |  |

<a id="attr-typeribbonchainmaterialexpression"></a>
### `TypeRibbonChainMaterialExpression` — TypeID 47

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonChainMaterialExpression`

| Field | Type | Notes |
|---|---|---|
| `unkn1_0` | U32 |  |
| `unkn1_1` | U32 |  |
| `unkn1_2` | U32 |  |
| `unkn1_3` | U32 |  |
| `unkn1_4` | U32 |  |
| `unkn1_5` | U32 |  |
| `unkn1_6` | U32 |  |
| `unkn1_7` | U32 |  |
| `unkn1_8` | U32 |  |
| `unkn1_9` | U32 |  |
| `unkn1_10` | U32 |  |
| `unkn1_12` | U32 |  |
| `unkn1_13` | U32 |  |
| `unkn1_14` | U32 |  |
| `unkn1_15` | U32 |  |
| `unkn1_16` | U32 |  |
| `unkn1_17` | U32 |  |
| `unkn1_18` | U32 |  |
| `materialExpressions` | [`EFXMaterialExpressionList`](#struct-efxmaterialexpressionlist) |  |

<a id="attr-typeribbonfixendmaterial"></a>
### `TypeRibbonFixEndMaterial` — TypeID 48

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonFixEndMaterial`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | U32 |  |
| `color1` | Color |  |
| `color2` | Color |  |
| `unkn3` | F32 |  |
| `unkn4` | ukn_type |  |
| `unkn5` | ukn_type |  |
| `unkn6` | ukn_type |  |
| `unkn7` | U32 |  |
| `unkn8` | F32 |  |
| `unkn9` | F32 |  |
| `unkn10` | F32 |  |
| `unkn11` | F32 |  |
| `unkn12` | F32 |  |
| `unkn13` | F32 |  |
| `unkn14` | F32 |  |
| `unkn15` | U32 |  |
| `unkn16` | F32 |  |
| `unkn17` | F32 |  |
| `unkn18` | U32 |  |
| `unkn19` | U32 |  |
| `unkn20` | U32 |  |
| `unkn21` | F32 |  |
| `unkn39` | Color |  |
| `unkn40` | Color |  |
| `unkn41` | Color |  |
| `unkn42` | F32 |  |
| `unkn43` | F32 |  |
| `unkn44` | F32 |  |
| `unkn45` | F32 |  |
| `unkn46` | F32 |  |
| `unkn47` | F32 |  |
| `unkn48` | F32 |  |
| `unkn49` | F32 |  |
| `unkn50` | F32 |  |
| `unkn51` | U32 |  |
| `material` | [`EfxMaterialStructBase`](#struct-efxmaterialstructbase) |  |

<a id="attr-typeribbonfixendmaterialclip"></a>
### `TypeRibbonFixEndMaterialClip` — TypeID 49

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonFixEndMaterialClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `1` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxMaterialClipData`](#struct-efxmaterialclipdata) |  |

<a id="attr-typeribbonfixendmaterialexpression"></a>
### `TypeRibbonFixEndMaterialExpression` — TypeID 50

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonFixEndMaterialExpression`

| Field | Type | Notes |
|---|---|---|
| `unkn1_0` | U32 |  |
| `unkn1_1` | U32 |  |
| `unkn1_2` | U32 |  |
| `unkn1_3` | U32 |  |
| `unkn1_4` | U32 |  |
| `unkn1_5` | U32 |  |
| `unkn1_6` | U32 |  |
| `unkn1_7` | U32 |  |
| `unkn1_8` | U32 |  |
| `unkn1_9` | U32 |  |
| `unkn1_10` | U32 |  |
| `unkn1_12` | U32 |  |
| `unkn1_13` | U32 |  |
| `unkn1_14` | U32 |  |
| `unkn1_15` | U32 |  |
| `unkn1_16` | U32 |  |
| `unkn1_17` | U32 |  |
| `unkn1_18` | U32 |  |
| `materialExpressions` | [`EFXMaterialExpressionList`](#struct-efxmaterialexpressionlist) |  |

<a id="attr-typeribbonparticlematerial"></a>
### `TypeRibbonParticleMaterial` — TypeID 57

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonParticleMaterial`

| Field | Type | Notes |
|---|---|---|
| `ukn1` | U32 |  |
| `color1` | Color |  |
| `color2` | Color |  |
| `ukn5` | F32 |  |
| `ukn6` | U32 |  |
| `ukn7` | U32 |  |
| `ukn8` | F32 |  |
| `ukn9` | U32 |  |
| `ukn10` | F32 |  |
| `ukn11` | F32 |  |
| `ukn12` | F32 |  |
| `ukn14` | F32 |  |
| `ukn15` | S32 |  |
| `ukn16` | F32 |  |
| `ukn17` | F32 |  |
| `ukn18` | F32 |  |
| `ukn19` | U32 |  |
| `ukn20` | U32 |  |
| `ukn21` | U32 |  |
| `ukn22` | F32 |  |
| `ukn23` | F32 |  |
| `ukn24` | F32 |  |
| `color3` | Color |  |
| `color4` | Color |  |
| `color5` | Color |  |
| `ukn25` | F32 |  |
| `ukn26` | F32 |  |
| `ukn27` | F32 |  |
| `ukn28` | F32 |  |
| `ukn29` | F32 |  |
| `ukn30` | F32 |  |
| `ukn31` | F32 |  |
| `ukn32` | F32 |  |
| `ukn33` | F32 |  |
| `ukn34` | U32 |  |
| `material` | [`EfxMaterialStructBase`](#struct-efxmaterialstructbase) |  |

<a id="attr-typeribbonparticlematerialclip"></a>
### `TypeRibbonParticleMaterialClip` — TypeID 58

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonParticleMaterialClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `1` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-typeribbonparticlematerialexpression"></a>
### `TypeRibbonParticleMaterialExpression` — TypeID 59

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonParticleMaterialExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `14` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `materialExpressionCount` | U32 |  |
| `materialExpressions` | [`EFXMaterialExpressionList`](#struct-efxmaterialexpressionlist) |  |

<a id="attr-typeribbonfollowexpression"></a>
### `TypeRibbonFollowExpression` — TypeID 60

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonFollowExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `17` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scale` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scaleRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-typeribbonlengthexpression"></a>
### `TypeRibbonLengthExpression` — TypeID 61

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonLengthExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `19` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `size1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `size2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `emissive` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `size` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-typeribbonchainexpression"></a>
### `TypeRibbonChainExpression` — TypeID 62

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonChainExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `17` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-typeribbonfixendexpression"></a>
### `TypeRibbonFixEndExpression` — TypeID 63

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonFixEndExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `17` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-typeribbonparticleexpression"></a>
### `TypeRibbonParticleExpression` — TypeID 65

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonParticleExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `17` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-typeribbontrail"></a>
### `TypeRibbonTrail` — TypeID 72

`ReeLib.Efx.Structs.Main.EFXAttributeTypeRibbonTrail`

| Field | Type | Notes |
|---|---|---|
| `BlendFlags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `Intensity` | F32 |  |
| `EdgeBlendRange` | F32 |  |
| `AlphaRate` | F32 |  |
| `Flags` | U32 |  |
| `Width` | Range |  |
| `ShadowMultiplier` | F32 |  |
| `Division` | U32 |  |
| `IntervalFrame` | U32 |  |

<a id="attr-typegpuribbonfollow"></a>
### `TypeGpuRibbonFollow` — TypeID 262

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuRibbonFollow`

| Field | Type | Notes |
|---|---|---|
| `BlendFlags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `Intensity` | F32 |  |
| `EdgeBlendRange` | F32 |  |
| `AlphaRate` | F32 |  |
| `FollowFlags` | U32 |  |
| `ParticleNum` | U32 |  |
| `SegmentNum` | U32 |  |
| `ControlPointNum` | U32 |  |
| `SizeScalar` | Range |  |
| `StretchDistance` | Vec2 |  |

<a id="attr-typegpuribbonfollowexpression"></a>
### `TypeGpuRibbonFollowExpression` — TypeID 263

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuRibbonFollowExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `9` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorRate` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `size` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `sizeRange` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-typegpuribbonlength"></a>
### `TypeGpuRibbonLength` — TypeID 264

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuRibbonLength`

| Field | Type | Notes |
|---|---|---|
| `BlendFlags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `Intensity` | F32 |  |
| `EdgeBlendRange` | F32 |  |
| `AlphaRate` | F32 |  |
| `Flags` | U32 |  |
| `SizeScalar` | Range |  |
| `Width` | Range |  |
| `TextureRepeatNum` | F32 |  |
| `ParticleNum` | U32 |  |
| `Length` | Range |  |
| `ShapeDivision` | U32 |  |
| `BasingPoint` | Range |  |
| `DirectionX` | Range |  |
| `DirectionY` | Range |  |
| `DirectionZ` | Range |  |

<a id="attr-typegpuribbonlengthexpression"></a>
### `TypeGpuRibbonLengthExpression` — TypeID 265

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuRibbonLengthExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `14` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alphaRate` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

## Transform attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxTransform.cs`_

<a id="attr-transform2d"></a>
### `Transform2D` — TypeID 5

`ReeLib.Efx.Structs.Transforms.EFXAttributeTransform2D`

| Field | Type | Notes |
|---|---|---|
| `LocalPosition` | Vec2 |  |
| `LocalRotation` | F32 |  |
| `LocalScale` | Vec2 |  |

<a id="attr-transform2dmodifierdelayframe"></a>
### `Transform2DModifierDelayFrame` — TypeID 6

`ReeLib.Efx.Structs.Transforms.EFXAttributeTransform2DModifierDelayFrame`

| Field | Type | Notes |
|---|---|---|
| `frameDelay` | U32 |  |
| `unkn1` | U32 |  |

<a id="attr-transform2dclip"></a>
### `Transform2DClip` — TypeID 8

`ReeLib.Efx.Structs.Transforms.EFXAttributeTransform2DClip`

| Field | Type | Notes |
|---|---|---|
| `ukn0` | U32 |  |
| `ukn1` | U32 |  |
| `ukn2` | U32 |  |
| `ukn3` | U32 |  |
| `ukn4` | U32 |  |
| `ukn5_0` | U32 |  |
| `ukn5_1` | U32 |  |
| `ukn5_2` | U32 |  |
| `ukn5_3` | U32 |  |
| `ukn5_4` | U32 |  |
| `ukn5_5` | U32 |  |
| `ukn5_6` | U32 |  |
| `ukn5_7` | U32 |  |
| `ukn5_8` | U32 |  |
| `ukn5_9` | U32 |  |
| `ukn5_10` | U32 |  |
| `ukn5_11` | U32 |  |
| `ukn5_12` | U32 |  |
| `ukn5_13` | U32 |  |
| `ukn5_14` | U32 |  |
| `ukn5_15` | U32 |  |
| `ukn5_16` | U32 |  |
| `ukn5_17` | U32 |  |
| `ukn5_18` | U32 |  |
| `ukn5_19` | U32 |  |
| `ukn5_20` | U32 |  |
| `ukn5_21` | U32 |  |
| `ukn5_22` | U32 |  |
| `ukn5_23` | U32 |  |
| `ukn5_24` | U32 |  |
| `ukn5_25` | U32 |  |
| `ukn5_26` | U32 |  |
| `ukn5_27` | U32 |  |
| `ukn5_28` | U32 |  |
| `ukn5_29` | U32 |  |
| `ukn5_30` | U32 |  |
| `ukn5_31` | U32 |  |
| `ukn5_32` | U32 |  |
| `ukn5_33` | U32 |  |
| `ukn6` | U8 |  |
| `ukn7_0` | U32 |  |
| `ukn7_1` | U32 |  |
| `ukn7_2` | U32 |  |
| `ukn7_3` | U32 |  |
| `ukn7_4` | U32 |  |
| `ukn7_5` | U32 |  |
| `ukn7_6` | U32 |  |
| `ukn8_0` | U8 |  |
| `ukn8_1` | U8 |  |
| `ukn9` | U32 |  |

<a id="attr-transform2dexpression"></a>
### `Transform2DExpression` — TypeID 9

`ReeLib.Efx.Structs.Transforms.EFXAttributeTransform2DExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `5` |
| `posX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rot` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scaleX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scaleY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-transform3d"></a>
### `Transform3D` — TypeID 10

`ReeLib.Efx.Structs.Transforms.EFXAttributeTransform3D`

| Field | Type | Notes |
|---|---|---|
| `LocalPosition` | Vec3 |  |
| `LocalRotation` | Vec3 |  |
| `LocalScale` | Vec3 |  |
| `RotationOrder` | S32 (enum [`RotationOrder`](#enum-rotationorder)) |  |

<a id="attr-transform3dmodifierdelayframe"></a>
### `Transform3DModifierDelayFrame` — TypeID 11

`ReeLib.Efx.Structs.Transforms.EFXAttributeTransform3DModifierDelayFrame`

| Field | Type | Notes |
|---|---|---|
| `frameDelay` | U32 |  |
| `unkn1` | U32 |  |

<a id="attr-transform3dmodifier"></a>
### `Transform3DModifier` — TypeID 12

`ReeLib.Efx.Structs.Transforms.EFXAttributeTransform3DModifier`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | U32 |  |
| `unkn1` | F32 |  |
| `unkn2` | F32 |  |
| `unkn3` | F32 |  |
| `unkn4` | F32 |  |
| `unkn5` | F32 |  |
| `unkn6` | F32 |  |
| `unkn7` | F32 |  |
| `unkn8` | F32 |  |
| `unkn9` | F32 |  |
| `unkn10` | F32 |  |
| `unkn11` | F32 |  |
| `unkn12` | F32 |  |
| `unkn13` | F32 |  |
| `unkn14` | F32 |  |
| `unkn15` | F32 |  |
| `unkn16` | F32 |  |
| `unkn17` | F32 |  |
| `unkn18` | F32 |  |
| `unkn19` | F32 |  |
| `unkn20` | F32 |  |
| `unkn21` | F32 |  |
| `unkn22` | ukn_type |  |
| `unkn23` | F32 |  |
| `unkn24` | F32 |  |
| `unkn25` | F32 |  |
| `unkn26` | ukn_type |  |
| `unkn27` | F32 |  |
| `unkn28` | F32 |  |
| `unkn29` | F32 |  |
| `unkn30` | F32 |  |
| `unkn31` | F32 |  |
| `unkn32` | F32 |  |
| `unkn33` | F32 |  |
| `unkn34` | ukn_type |  |
| `unkn35` | F32 |  |
| `unkn36` | F32 |  |
| `unkn37` | F32 |  |
| `unkn38` | F32 |  |
| `unkn39` | F32 |  |
| `unkn40` | F32 |  |
| `unkn41` | F32 |  |
| `unkn42` | F32 |  |
| `unkn43` | F32 |  |
| `unkn44` | F32 |  |
| `unkn45` | F32 |  |
| `unkn46` | ukn_type |  |
| `unkn47` | F32 |  |
| `unkn48` | ukn_type |  |
| `unkn49` | F32 |  |
| `unkn50` | ukn_type |  |
| `unkn51` | F32 |  |
| `unkn52` | F32 |  |
| `unkn53` | F32 |  |
| `unkn54` | ukn_type |  |

<a id="attr-transform3dclip"></a>
### `Transform3DClip` — TypeID 13

`ReeLib.Efx.Structs.Transforms.EFXAttributeTransform3DClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `9` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-transform3dexpression"></a>
### `Transform3DExpression` — TypeID 14

`ReeLib.Efx.Structs.Transforms.EFXAttributeTransform3DExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `9` |
| `translationX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `translationY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `translationZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rotationX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rotationY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rotationZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scaleX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scaleY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scaleZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-rotateanimdelayframe"></a>
### `RotateAnimDelayFrame` — TypeID 86

`ReeLib.Efx.Structs.Transforms.EFXAttributeRotateAnimDelayFrame`

| Field | Type | Notes |
|---|---|---|
| `frameDelay` | U32 |  |
| `unkn2` | U32 |  |

<a id="attr-rotateanim"></a>
### `RotateAnim` — TypeID 87

`ReeLib.Efx.Structs.Transforms.EFXAttributeRotateAnim`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `RotationAddX` | Range |  |
| `RotationAddY` | Range |  |
| `RotationAddZ` | Range |  |
| `RotationCoefX` | Range |  |
| `RotationCoefY` | Range |  |
| `RotationCoefZ` | Range |  |
| `RotationDelayFrame` | RangeI |  |

<a id="attr-rotateanimexpression"></a>
### `RotateAnimExpression` — TypeID 88

`ReeLib.Efx.Structs.Transforms.EFXAttributeRotateAnimExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `12` |
| `rotateSpeedX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rotateSpeedXRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rotateSpeedY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rotateSpeedYRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rotateSpeedZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rotateSpeedZRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn1_7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn1_8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn1_9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn1_10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn1_11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn1_12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-scaleanimdelayframe"></a>
### `ScaleAnimDelayFrame` — TypeID 89

`ReeLib.Efx.Structs.Transforms.EFXAttributeScaleAnimDelayFrame`

| Field | Type | Notes |
|---|---|---|
| `frameDelay` | U32 |  |
| `unkn2` | U32 |  |

<a id="attr-scaleanim"></a>
### `ScaleAnim` — TypeID 90

`ReeLib.Efx.Structs.Transforms.EFXAttributeScaleAnim`

| Field | Type | Notes |
|---|---|---|
| `SizeScalarAdd` | Range |  |
| `SizeScalarCoef` | Range |  |
| `SizeXAdd` | Range |  |
| `SizeXAddCoef` | Range |  |
| `SizeYAdd` | Range |  |
| `SizeYAddCoef` | Range |  |
| `SizeZAdd` | Range |  |
| `SizeZAddCoef` | Range |  |
| `SizeDelayFrame` | RangeI |  |

<a id="attr-scaleanimexpression"></a>
### `ScaleAnimExpression` — TypeID 91

`ReeLib.Efx.Structs.Transforms.EFXAttributeScaleAnimExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `8` |
| `scale` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scaleRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-scalebydepth"></a>
### `ScaleByDepth` — TypeID 150

`ReeLib.Efx.Structs.Transforms.EFXAttributeScaleByDepth`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `NearStart` | F32 |  |
| `NearEnd` | F32 |  |
| `NearScale` | F32 |  |
| `FarStart` | F32 |  |
| `FarEnd` | F32 |  |
| `FarScale` | F32 |  |

<a id="attr-pttransform3d"></a>
### `PtTransform3D` — TypeID 159

`ReeLib.Efx.Structs.Transforms.EFXAttributePtTransform3D`

| Field | Type | Notes |
|---|---|---|
| `position` | Vec3 |  |
| `rotation` | Vec3 |  |
| `scale` | Vec3 |  |

<a id="attr-pttransform3dclip"></a>
### `PtTransform3DClip` — TypeID 160

`ReeLib.Efx.Structs.Transforms.EFXAttributePtTransform3DClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `9` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-pttransform3dexpression"></a>
### `PtTransform3DExpression` — TypeID 161

`ReeLib.Efx.Structs.Transforms.EFXAttributePtTransform3DExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `9` |
| `posX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rotationX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rotationY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rotationZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scaleX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scaleY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scaleZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-pttransform2d"></a>
### `PtTransform2D` — TypeID 162

`ReeLib.Efx.Structs.Transforms.EFXAttributePtTransform2D`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | F32 |  |
| `unkn1` | F32 |  |
| `unkn2` | ukn_type |  |
| `unkn3` | F32 |  |
| `unkn4` | F32 |  |

<a id="attr-pttransform2dclip"></a>
### `PtTransform2DClip` — TypeID 163

`ReeLib.Efx.Structs.Transforms.EFXAttributePtTransform2DClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `5` |
| `unkn1` | ukn_type |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

## Basic / lifecycle attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxBasics.cs`_

<a id="attr-parentoptions"></a>
### `ParentOptions` — TypeID 15

`ReeLib.Efx.Structs.Basic.EFXAttributeParentOptions`

| Field | Type | Notes |
|---|---|---|
| `RelationPos` | Int3 |  |
| `RelationRot` | Int3 |  |
| `RelationScl` | Int3 |  |
| `ParticleUseLocal` | U8 |  |
| `ConstInheritRate` | Range |  |
| `ConstFrame` | RangeI |  |
| `ConstReleaseFrame` | RangeI |  |
| `ConstInheritReleaseRate` | F32 |  |
| `BoneName` | String |  |

<a id="attr-parentoptionsexpression"></a>
### `ParentOptionsExpression` — TypeID 16

`ReeLib.Efx.Structs.Basic.EFXAttributeParentOptionsExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `8` |
| `unkn1_1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn1_2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn1_3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn1_4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn1_5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn1_6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn1_7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn1_8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-spawn"></a>
### `Spawn` — TypeID 17

`ReeLib.Efx.Structs.Basic.EFXAttributeSpawn`

| Field | Type | Notes |
|---|---|---|
| `MaxParticles` | U32 |  |
| `ParticleInterval` | U32 |  |
| `SpawnNum` | Int2 |  |
| `IntervalFrame` | Int2 |  |
| `UseSpawnFrame` | Bool |  |
| `SpawnFrame` | RangeI |  |
| `LoopNum` | RangeI |  |
| `EmitterDelayFrame` | Int2 |  |
| `RingBufferMode` | Bool |  |
| `UseLoopNumRatio` | Bool |  |
| `Interpolate` | Bool |  |
| `DistancePerSpawn` | F32 |  |
| `UseRevival` | Bool |  |
| `RevivalNum` | RangeI |  |
| `RevivalInterval` | RangeI |  |
| `TrySpawnAllParticles` | Bool |  |
| `SpawnChanceFrame` | U32 |  |
| `InitializeFull` | Bool |  |
| `OriginalMaxParticles` | U32 |  |
| `mhws_unkn_toggle` | U8 |  |

<a id="attr-spawnexpression"></a>
### `SpawnExpression` — TypeID 18

`ReeLib.Efx.Structs.Basic.EFXAttributeSpawnExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `7` |
| `spawnNum` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `spawnNumRange` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `intervalFrame` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `intervalFrameRange` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `emitterDelayFrame` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `emitterDelayFrameRange` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `speed` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-life"></a>
### `Life` — TypeID 94

`ReeLib.Efx.Structs.Basic.EFXAttributeLife`

| Field | Type | Notes |
|---|---|---|
| `AppearFrame` | RangeI |  |
| `KeepFrame` | RangeI |  |
| `VanishFrame` | RangeI |  |
| `KeepHoldFrame` | RangeI |  |
| `Flags` | U32 |  |

<a id="attr-lifeexpression"></a>
### `LifeExpression` — TypeID 95

`ReeLib.Efx.Structs.Basic.EFXAttributeLifeExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `6` |
| `appearLife` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `appearLifeRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `keepLife` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `keepLifeRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `vanishLife` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `vanishLifeRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-uvsequence"></a>
### `UVSequence` — TypeID 96

`ReeLib.Efx.Structs.Basic.EFXAttributeUVSequence`

| Field | Type | Notes |
|---|---|---|
| `SequenceNo` | RangeI |  |
| `PatternNo` | RangeI |  |
| `PlaySpeed` | Range |  |
| `Flags` | U32 |  |
| `UVSPath` | String |  |

<a id="attr-uvsequencemodifier"></a>
### `UVSequenceModifier` — TypeID 97

`ReeLib.Efx.Structs.Basic.EFXAttributeUVSequenceModifier`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `PlaySpeedInit` | Range |  |
| `PlaySpeedFinal` | Range |  |
| `PlaySpeedChangeTimeCoef` | Range |  |

<a id="attr-uvsequenceexpression"></a>
### `UVSequenceExpression` — TypeID 98

`ReeLib.Efx.Structs.Basic.EFXAttributeUVSequenceExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `6` |
| `speed` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `speedRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-uvscroll"></a>
### `UVScroll` — TypeID 99

`ReeLib.Efx.Structs.Basic.EFXAttributeUVScroll`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `uScrollAdd` | Range |  |
| `vScrollAdd` | Range |  |
| `uScrollAddCoef` | Range |  |
| `vScrollAddCoef` | Range |  |
| `uScrollOffset` | Range |  |
| `vScrollOffset` | Range |  |

<a id="attr-textureunit"></a>
### `TextureUnit` — TypeID 100

`ReeLib.Efx.Structs.Basic.EFXAttributeTextureUnit`

| Field | Type | Notes |
|---|---|---|
| `unkn1` | U32 |  |
| `texUnit1` | [`TextureUnitData`](#struct-textureunitdata) |  |
| `texUnit2` | [`TextureUnitData`](#struct-textureunitdata) |  |
| `texUnit3` | [`TextureUnitData`](#struct-textureunitdata) |  |
| `uvs0PathCharCount` | S32 | StringLength → `uvs0Path` |
| `uvs1PathCharCount` | S32 | StringLength → `uvs1Path` |
| `uvs2PathCharCount` | S32 | StringLength → `uvs2Path` |
| `uvs0Path` | String |  |
| `uvs1Path` | String |  |
| `uvs2Path` | String |  |

<a id="attr-textureunitexpression"></a>
### `TextureUnitExpression` — TypeID 101

`ReeLib.Efx.Structs.Basic.EFXAttributeTextureUnitExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[4] | BitSet → `114` |
| `assignTypes` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype))[114] |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-texturefilter"></a>
### `TextureFilter` — TypeID 102

`ReeLib.Efx.Structs.Basic.EFXAttributeTextureFilter`

| Field | Type | Notes |
|---|---|---|
| `TexelAlphaRate` | F32 |  |
| `TexelAlphaHPThreshold` | F32 |  |
| `TexelAlphaHPMinValue` | F32 |  |

<a id="attr-alphacorrection"></a>
### `AlphaCorrection` — TypeID 107

`ReeLib.Efx.Structs.Basic.EFXAttributeAlphaCorrection`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `LowPass` | F32 |  |
| `HighPass` | F32 |  |
| `CurveConst` | F32 |  |

<a id="attr-shadersettings"></a>
### `ShaderSettings` — TypeID 127

`ReeLib.Efx.Structs.Basic.EFXAttributeShaderSettings`

| Field | Type | Notes |
|---|---|---|
| `Saturation` | F32 |  |
| `unkn2` | U32 |  |
| `re8_unkn1` | F32 |  |
| `re8_unkn2` | F32 |  |
| `LayerNegative` | F32 |  |
| `re8_unkn000` | U32 |  |
| `color0` | Color |  |
| `unkn6` | F32 |  |
| `unkn7` | F32 |  |
| `unkn8` | F32 |  |
| `unkn9` | F32 |  |
| `unkn10` | F32 |  |
| `unkn11` | F32 |  |
| `unkn12` | F32 |  |
| `unkn13` | U32 |  |
| `unkn14` | U32 |  |
| `unkn15` | F32 |  |
| `unkn16` | F32 |  |
| `unkn17` | F32 |  |
| `re4_unkn1` | F32 |  |
| `re4_unkn2` | F32 |  |
| `re4_unkn3` | F32 |  |
| `sb_unkn2` | F32 |  |
| `sb_unkn3` | F32 |  |
| `sb_unkn4` | F32 |  |
| `sb_unkn5` | F32 |  |
| `dd2_unkn1` | F32 |  |
| `ColorBrightness` | F32 |  |
| `toggle_dd2` | U32 |  |
| `unkn21` | F32 |  |
| `sb_unkn9` | F32 |  |
| `sb_unkn10` | F32 |  |
| `sb_unkn11` | F32 |  |
| `sb_unkn12` | F32 |  |
| `dd2_unkn2` | F32 |  |
| `unkn22` | U32 |  |
| `unkn24` | U32 |  |
| `mhws_unkn1` | F32 |  |
| `mhws_unkn2` | F32 |  |
| `mhws_unkn_short` | S16 |  |

<a id="attr-shadersettingsexpression"></a>
### `ShaderSettingsExpression` — TypeID 128

`ReeLib.Efx.Structs.Basic.EFXAttributeShaderSettingsExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `12` |
| `ukn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-rendertarget"></a>
### `RenderTarget` — TypeID 132

`ReeLib.Efx.Structs.Basic.EFXAttributeRenderTarget`

| Field | Type | Notes |
|---|---|---|
| `unkn_toggle` | U32 |  |
| `rtexPath` | String |  |

<a id="attr-playefx"></a>
### `PlayEfx` — TypeID 139

`ReeLib.Efx.Structs.Basic.EFXAttributePlayEfx`

| Field | Type | Notes |
|---|---|---|
| `efxPath` | String |  |

<a id="attr-playemitter"></a>
### `PlayEmitter` — TypeID 158

`ReeLib.Efx.Structs.Basic.EFXAttributePlayEmitter`

| Field | Type | Notes |
|---|---|---|
| `efxrSize` | U32 | StructSize → `efxrData` |
| `efxrData` | Data (`EfxFile`)[] | EmbeddedEFX |

## Velocity attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxVelocity.cs`_

<a id="attr-velocity2ddelayframe"></a>
### `Velocity2DDelayFrame` — TypeID 80

`ReeLib.Efx.Structs.Transforms.EFXAttributeVelocity2DDelayFrame`

| Field | Type | Notes |
|---|---|---|
| `DelayFrames` | U32 |  |
| `Unkn1` | U32 |  |

<a id="attr-velocity2d"></a>
### `Velocity2D` — TypeID 81

`ReeLib.Efx.Structs.Transforms.EFXAttributeVelocity2D`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `unkn1_0` | F32 |  |
| `unkn1_1` | F32 |  |
| `unkn1_2` | F32 |  |
| `unkn1_3` | F32 |  |
| `unkn1_4` | F32 |  |
| `unkn1_5` | F32 |  |
| `unkn1_6` | F32 |  |
| `re4_unkn0` | U32 |  |
| `unkn1_7` | F32 |  |
| `re4_unkn1` | F32 |  |
| `unkn2_0` | F32 |  |
| `unkn2_1` | F32 |  |
| `unkn2_2` | U32 |  |
| `unkn2_3` | F32 |  |
| `unkn2_4` | F32 |  |
| `re4_unkn2_0` | U32 |  |
| `re4_unkn2_1` | U32 |  |

<a id="attr-velocity2dexpression"></a>
### `Velocity2DExpression` — TypeID 82

`ReeLib.Efx.Structs.Transforms.EFXAttributeVelocity2DExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `13` |
| `speed` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `speedRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `gravity` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `angle` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `angleRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-velocity3ddelayframe"></a>
### `Velocity3DDelayFrame` — TypeID 83

`ReeLib.Efx.Structs.Transforms.EFXAttributeVelocity3DDelayFrame`

| Field | Type | Notes |
|---|---|---|
| `frameDelay` | U32 |  |
| `unkn2` | U32 |  |

<a id="attr-velocity3d"></a>
### `Velocity3D` — TypeID 84

`ReeLib.Efx.Structs.Transforms.EFXAttributeVelocity3D`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `DirectionVectorX` | Range |  |
| `DirectionVectorY` | Range |  |
| `DirectionVectorZ` | Range |  |
| `Speed` | Range |  |
| `SpeedCoef` | Range |  |
| `SpeedDelayFrame` | RangeI |  |
| `Offset` | Vec3 |  |
| `Size` | Vec3 |  |
| `VelocityType` | S32 (enum [`VelocityType`](#enum-velocitytype)) |  |
| `GravityRate` | Range |  |
| `GravityDelayFrame` | RangeI |  |
| `InheritRate` | Range |  |
| `InheritDistance` | Range |  |
| `Spread` | Range |  |

<a id="attr-velocity3dexpression"></a>
### `Velocity3DExpression` — TypeID 85

`ReeLib.Efx.Structs.Transforms.EFXAttributeVelocity3DExpression`

| Field | Type | Notes |
|---|---|---|
| `rert_unkn0` | U32 |  |
| `rert_unkn1` | U32 |  |
| `range1` | Vec2 |  |
| `range2` | Vec2 |  |
| `range3` | Vec2 |  |
| `expressionBits` | U32[1] | BitSet → `19` |
| `speed` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `speedRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `velocityX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `velocityXRandom` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `velocityY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `velocityYRandom` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `velocityZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `velocityZRandom` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-ptvelocity3d"></a>
### `PtVelocity3D` — TypeID 164

`ReeLib.Efx.Structs.Transforms.EFXAttributePtVelocity3D`

| Field | Type | Notes |
|---|---|---|
| `unkn1_0` | F32 |  |
| `unkn1_1` | F32 |  |
| `unkn1_2` | F32 |  |
| `unkn1_3` | F32 |  |

<a id="attr-ptvelocity3dclip"></a>
### `PtVelocity3DClip` — TypeID 165

`ReeLib.Efx.Structs.Transforms.EFXAttributePtVelocity3DClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `4` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-ptvelocity2d"></a>
### `PtVelocity2D` — TypeID 166

`ReeLib.Efx.Structs.Transforms.EFXAttributePtVelocity2D`

| Field | Type | Notes |
|---|---|---|
| `ukn0` | F32 |  |
| `ukn1` | F32 |  |
| `ukn2` | F32 |  |

<a id="attr-ptvelocity2dclip"></a>
### `PtVelocity2DClip` — TypeID 167

`ReeLib.Efx.Structs.Transforms.EFXAttributePtVelocity2DClip`

| Field | Type | Notes |
|---|---|---|
| `ukn0` | U32 |  |
| `ukn1` | F32 |  |
| `ukn2` | F32 |  |
| `ukn3` | U32 |  |

<a id="attr-angularvelocity3ddelayframe"></a>
### `AngularVelocity3DDelayFrame` — TypeID 220

`ReeLib.Efx.Structs.Transforms.EFXAttributeAngularVelocity3DDelayFrame`

| Field | Type | Notes |
|---|---|---|
| `frameDelay` | U32 |  |
| `unkn1` | U32 |  |

<a id="attr-angularvelocity3d"></a>
### `AngularVelocity3D` — TypeID 221

`ReeLib.Efx.Structs.Transforms.EFXAttributeAngularVelocity3D`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `RotationOrder` | S32 (enum [`RotationOrder`](#enum-rotationorder)) |  |
| `Radius` | Range |  |
| `AddRadius` | Range |  |
| `AddRadiusCoef` | F32 |  |
| `RotationAxisX` | Range |  |
| `RotationAxisY` | Range |  |
| `RotationAxisZ` | Range |  |
| `AddRotationAxisX` | Range |  |
| `AddRotationAxisY` | Range |  |
| `AddRotationAxisZ` | Range |  |
| `AddRotationCoef` | F32 |  |

<a id="attr-ptangularvelocity3d"></a>
### `PtAngularVelocity3D` — TypeID 222

`ReeLib.Efx.Structs.Transforms.EFXAttributePtAngularVelocity3D`

| Field | Type | Notes |
|---|---|---|
| `unkn1` | ukn_type |  |
| `unkn2` | F32 |  |
| `unkn3` | F32 |  |
| `unkn4` | ukn_type |  |
| `unkn5` | ukn_type |  |
| `unkn6` | ukn_type |  |
| `unkn7` | F32 |  |
| `unkn8` | F32 |  |

<a id="attr-ptangularvelocity3dexpression"></a>
### `PtAngularVelocity3DExpression` — TypeID 223

`ReeLib.Efx.Structs.Transforms.EFXAttributePtAngularVelocity3DExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `7` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-angularvelocity2ddelayframe"></a>
### `AngularVelocity2DDelayFrame` — TypeID 224

`ReeLib.Efx.Structs.Transforms.EFXAttributeAngularVelocity2DDelayFrame`

| Field | Type | Notes |
|---|---|---|
| `DelayFrames` | U32 |  |
| `Unkn1` | U32 |  |

<a id="attr-angularvelocity2d"></a>
### `AngularVelocity2D` — TypeID 225

`ReeLib.Efx.Structs.Transforms.EFXAttributeAngularVelocity2D`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | U32 |  |
| `unkn1` | F32 |  |
| `unkn2` | F32 |  |
| `unkn3` | F32 |  |
| `unkn4` | F32 |  |
| `unkn5` | F32 |  |
| `unkn6` | F32 |  |
| `unkn7` | F32 |  |
| `unkn8` | F32 |  |
| `unkn9` | F32 |  |
| `unkn10` | F32 |  |
| `unkn11` | F32 |  |
| `radians12` | F32 |  |
| `radians13` | F32 |  |
| `radians14` | F32 |  |

<a id="attr-ptangularvelocity2d"></a>
### `PtAngularVelocity2D` — TypeID 226

`ReeLib.Efx.Structs.Transforms.EFXAttributePtAngularVelocity2D`

| Field | Type | Notes |
|---|---|---|
| `unkn1` | F32 |  |
| `unkn2` | F32 |  |
| `unkn3` | F32 |  |
| `unkn4` | F32 |  |
| `unkn5` | F32 |  |
| `unkn6` | F32 |  |

<a id="attr-ptangularvelocity2dexpression"></a>
### `PtAngularVelocity2DExpression` — TypeID 227

`ReeLib.Efx.Structs.Transforms.EFXAttributePtAngularVelocity2DExpression`

| Field | Type | Notes |
|---|---|---|
| `unkn1` | U32 |  |
| `unkn2` | U32 |  |
| `unkn3` | U32 |  |
| `unkn4` | U32 |  |
| `unkn5` | U32 |  |
| `unkn6` | U32 |  |
| `unkn7` | U32 |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

## Particle (Pt) behavior attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxPtBehavior.cs`_

<a id="attr-ptsort"></a>
### `PtSort` — TypeID 22

`ReeLib.Efx.Structs.Pt.EFXAttributePtSort`

| Field | Type | Notes |
|---|---|---|
| `SortType` | S32 (enum [`SortType`](#enum-sorttype)) |  |

<a id="attr-ptlightningcollideraction"></a>
### `PtLightningColliderAction` — TypeID 125

`ReeLib.Efx.Structs.Pt.EFXAttributePtLightningColliderAction`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `unkn2` | F32 |  |
| `unkn3` | U32 |  |

<a id="attr-ptlife"></a>
### `PtLife` — TypeID 136

`ReeLib.Efx.Structs.Pt.EFXAttributePtLife`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Status` | U32 |  |
| `ActionIndex` | S32 |  |

<a id="attr-ptbehavior"></a>
### `PtBehavior` — TypeID 137

`ReeLib.Efx.Structs.Pt.EFXAttributePtBehavior`

| Field | Type | Notes |
|---|---|---|
| `unkn1` | U32 |  |
| `behaviorStringLength` | S32 | StringLength → `behaviorString` |
| `behaviorString` | String |  |
| `varCount_mhws` | S32 | StructSize → `properties` |
| `properties` | [`PtBehaviorVariable`](#struct-ptbehaviorvariable)[] |  |

<a id="attr-ptcollideraction"></a>
### `PtColliderAction` — TypeID 168

`ReeLib.Efx.Structs.Pt.EFXAttributePtColliderAction`

| Field | Type | Notes |
|---|---|---|
| `dataFlags` | U32 |  |
| `unkn1` | F32 |  |
| `unkn2` | F32 |  |
| `linkedAction` | U32 |  |
| `ukn_flag2_0` | U32 |  |
| `ukn_flag2_2` | F32 |  |
| `ukn_flag2_3` | F32 |  |
| `ukn_flag2_4` | F32 |  |
| `ukn_flag2_5` | F32 |  |
| `ukn_flag2_6` | U32 |  |
| `ukn_flag2_7` | F32 |  |
| `ukn_flag2_8` | F32 |  |
| `ukn_flag2_9` | F32 |  |
| `ukn_flag2_10` | F32 |  |
| `ukn_flag2_11` | F32 |  |
| `dd2_unkn0` | U32 |  |
| `dd2_unkn1` | U32 |  |
| `unknString_flag2` | String |  |
| `unknString_flag1` | String |  |
| `wilds_unkn0` | U32 |  |

<a id="attr-ptprojection"></a>
### `PtProjection` — TypeID 169

`ReeLib.Efx.Structs.Pt.EFXAttributePtProjection`

| Field | Type | Notes |
|---|---|---|
| `flags` | U32 |  |
| `unkn2` | F32 |  |
| `unkn3` | F32 |  |
| `unkn4` | F32 |  |
| `unkn5` | F32 |  |
| `unkn6` | ukn_type |  |
| `unkn7` | ukn_type |  |
| `unknString0` | String |  |

<a id="attr-ptcollision"></a>
### `PtCollision` — TypeID 170

`ReeLib.Efx.Structs.Pt.EFXAttributePtCollision`

| Field | Type | Notes |
|---|---|---|
| `stringBitFlag` | U8 |  |
| `unkn0_1` | U8 |  |
| `unkn0_2` | U8 |  |
| `unkn0_3` | U8 |  |
| `Radius` | Range |  |
| `BounceNum` | RangeI |  |
| `BounceRate` | Range |  |
| `VerticalBounce` | F32 |  |
| `HorizontalBounce` | F32 |  |
| `FinishType` | S32 (enum [`Finish`](#enum-finish)) |  |
| `projectionOffset` | F32 |  |
| `projectionDist` | F32 |  |
| `unkn12` | F32 |  |
| `unknString0` | String |  |
| `unknString1` | String |  |

<a id="attr-ptcollisioninfluence"></a>
### `PtCollisionInfluence` — TypeID 171

`ReeLib.Efx.Structs.Pt.EFXAttributePtCollisionInfluence`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Unkn1` | U32 |  |
| `Unkn2` | U32 |  |
| `Unkn3` | U32 |  |
| `Unkn4` | U32 |  |
| `Unkn5` | U32 |  |
| `Unkn6` | U32 |  |
| `Unkn7` | F32 |  |
| `Unkn8` | U32 |  |
| `len_Data` | S32 | StructSize → `Data` |
| `Data` | [`EFXAttributePtCollisionInfluence+PtCollisionInfluenceData`](#struct-efxattributeptcollisioninfluenceptcollisioninfluencedata)[] |  |

<a id="attr-ptcolor"></a>
### `PtColor` — TypeID 172

`ReeLib.Efx.Structs.Pt.EFXAttributePtColor`

| Field | Type | Notes |
|---|---|---|
| `ColorOperator` | S32 (enum [`PtColorOperator`](#enum-ptcoloroperator)) |  |
| `AlphaOperator` | S32 (enum [`PtColorOperator`](#enum-ptcoloroperator)) |  |
| `Color` | Color |  |

<a id="attr-ptcolorclip"></a>
### `PtColorClip` — TypeID 173

`ReeLib.Efx.Structs.Pt.EFXAttributePtColorClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `4` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-ptcolormixer"></a>
### `PtColorMixer` — TypeID 174

`ReeLib.Efx.Structs.Pt.EFXAttributePtColorMixer`

| Field | Type | Notes |
|---|---|---|
| `Unkn0` | U32 |  |
| `colorCount` | S32 | StructSize → `Colors` |
| `Unkn2` | U32 |  |
| `Unkn3` | F32 |  |
| `Colors` | Color[] |  |

<a id="attr-ptuvsequence"></a>
### `PtUvSequence` — TypeID 176

`ReeLib.Efx.Structs.Pt.EFXAttributePtUvSequence`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `PatternNo` | U32 |  |
| `PlaySpeed` | F32 |  |

<a id="attr-ptuvsequenceclip"></a>
### `PtUvSequenceClip` — TypeID 177

`ReeLib.Efx.Structs.Pt.EFXAttributePtUvSequenceClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `3` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-ptvortexelheatsource"></a>
### `PtVortexelHeatSource` — TypeID 207

`ReeLib.Efx.Structs.Pt.EFXAttributePtVortexelHeatSource`

| Field | Type | Notes |
|---|---|---|
| `Unkn0` | F32 |  |
| `unkn1` | S32 |  |
| `unkn2` | S16 |  |
| `unkn3` | U32 |  |

<a id="attr-ptpathtranslate"></a>
### `PtPathTranslate` — TypeID 228

`ReeLib.Efx.Structs.Pt.EFXAttributePtPathTranslate`

| Field | Type | Notes |
|---|---|---|
| `unkn1` | U32 |  |
| `unkn2` | U32 |  |
| `unkn3` | F32 |  |
| `dataSize` | S32 |  |
| `unkn4` | F32 |  |
| `unkn5` | F32 |  |
| `unkn6` | F32 |  |
| `unkn7` | F32 |  |
| `unkn8` | F32 |  |
| `unkn9` | F32 |  |
| `unkn10` | F32 |  |
| `unkn11` | F32 |  |
| `unkn12` | F32 |  |
| `rotation` | Vec3 |  |
| `scale` | Vec3 |  |
| `substruct2` | [`EFXAttributePtPathTranslate+PtPathTranslateSubstruct`](#struct-efxattributeptpathtranslateptpathtranslatesubstruct)[] |  |
| `nameFlags` | U32 |  |
| `names` | [`PtPathTranslateName`](#struct-ptpathtranslatename)[] |  |

<a id="attr-ptpathtranslateexpression"></a>
### `PtPathTranslateExpression` — TypeID 229

`ReeLib.Efx.Structs.Pt.EFXAttributePtPathTranslateExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `4` |
| `Field1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `Field2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `Field3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `Field4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-ptfreezer"></a>
### `PtFreezer` — TypeID 246

`ReeLib.Efx.Structs.Pt.EFXAttributePtFreezer`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | U32 |  |
| `unkn1` | U32 |  |
| `unkn2` | U32 |  |
| `unkn3` | U32 |  |
| `unkn4` | U32 |  |
| `unkn5` | U32 |  |
| `unkn6` | ukn_type |  |
| `unkn7` | ukn_type |  |
| `unkn8` | U32 |  |
| `unkn9` | ukn_type |  |

## Emitter attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxEmitter.cs`_

<a id="attr-emittercolor"></a>
### `EmitterColor` — TypeID 19

`ReeLib.Efx.Structs.Transforms.EFXAttributeEmitterColor`

| Field | Type | Notes |
|---|---|---|
| `ColorOperator` | S32 (enum [`EmitterColorOperator`](#enum-emittercoloroperator)) |  |
| `AlphaOperator` | S32 (enum [`EmitterColorOperator`](#enum-emittercoloroperator)) |  |
| `Color` | Color |  |

<a id="attr-emittercolorclip"></a>
### `EmitterColorClip` — TypeID 20

`ReeLib.Efx.Structs.Transforms.EFXAttributeEmitterColorClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `4` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-emittershape2d"></a>
### `EmitterShape2D` — TypeID 103

`ReeLib.Efx.Structs.Transforms.EFXAttributeEmitterShape2D`

| Field | Type | Notes |
|---|---|---|
| `RangeX` | Range |  |
| `RangeY` | Range |  |
| `ShapeType` | S32 (enum [`Shape2DType`](#enum-shape2dtype)) |  |
| `RangeDivideNum` | U32 |  |
| `DivideAxis` | S32 (enum [`AxisXYZ`](#enum-axisxyz)) |  |
| `LocalRotation` | F32 |  |

<a id="attr-emittershape2dexpression"></a>
### `EmitterShape2DExpression` — TypeID 104

`ReeLib.Efx.Structs.Transforms.EFXAttributeEmitterShape2DExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `5` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `size` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-emittershape3d"></a>
### `EmitterShape3D` — TypeID 105

`ReeLib.Efx.Structs.Transforms.EFXAttributeEmitterShape3D`

| Field | Type | Notes |
|---|---|---|
| `RangeX` | Range |  |
| `RangeY` | Range |  |
| `RangeZ` | Range |  |
| `ShapeType` | S32 (enum [`Shape3DType`](#enum-shape3dtype)) |  |
| `RangeDivideNum` | U32 |  |
| `RangeDivideAxis` | S32 (enum [`AxisXYZ`](#enum-axisxyz)) |  |
| `RangeDivideHorizontalNum` | U32 |  |
| `RangeDivideVerticalNum` | U32 |  |
| `LocalRotation` | Vec3 |  |
| `RotationOrder` | S32 (enum [`RotationOrder`](#enum-rotationorder)) |  |
| `RotationCorrect` | S32 (enum [`RotationCorrectType`](#enum-rotationcorrecttype)) |  |
| `DivideEquidistant` | Bool |  |
| `DivideEquidistantCalcOuterCurveData` | Bool |  |
| `DivideEquidistantRecalcEveryFrameData` | Bool |  |
| `UseExtension` | Bool |  |
| `ScaleHorizontal` | Range |  |
| `ScaleVertical` | Range |  |

<a id="attr-emittershape3dexpression"></a>
### `EmitterShape3DExpression` — TypeID 106

`ReeLib.Efx.Structs.Transforms.EFXAttributeEmitterShape3DExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `9` |
| `rangeXMin` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeXMax` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeYMin` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeYMax` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeZMin` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeZMax` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `spawnNum` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-meshemitter"></a>
### `MeshEmitter` — TypeID 178

`ReeLib.Efx.Structs.Transforms.EFXAttributeMeshEmitterV2`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `YNormalRange` | F32 |  |
| `PartsNumber` | S32 |  |
| `ClusterNumber` | S32 |  |
| `RotationOrder` | S32 (enum [`RotationOrder`](#enum-rotationorder)) |  |
| `LocalScale` | Vec3 |  |
| `LocalRotation` | Vec3 |  |
| `EmissionThreshold` | F32 |  |
| `EmissionVertexColorThreshold` | F32 |  |
| `EmissionVertexColorChannel` | U32 |  |
| `EmissionMaskMapColorChannel` | U32 |  |
| `ParticleNum` | U32 |  |
| `LodIndex` | U32 |  |
| `TriangleFilter` | F32 |  |
| `ColorUTilingCount` | U32 |  |
| `ColorVTilingCount` | U32 |  |
| `ColorUVOffset` | Vec2 |  |
| `MaskUTilingCount` | U32 |  |
| `MaskVTilingCount` | U32 |  |
| `MaskUVOffset` | Vec2 |  |
| `DynamicColorMapPath` | String |  |
| `MeshPath` | String |  |
| `MeshMirrorPath` | String |  |
| `ColorMapPath` | String |  |
| `MaskMapPath` | String |  |
| `TargetGameObjectName` | String |  |

<a id="attr-meshemitterclip"></a>
### `MeshEmitterClip` — TypeID 179

`ReeLib.Efx.Structs.Transforms.EFXAttributeMeshEmitterClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `9` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-meshemitterexpression"></a>
### `MeshEmitterExpression` — TypeID 180

`ReeLib.Efx.Structs.Transforms.EFXAttributeMeshEmitterExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `16` |
| `emitRate` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-screenspaceemitter"></a>
### `ScreenSpaceEmitter` — TypeID 181

`ReeLib.Efx.Structs.Transforms.EFXAttributeScreenSpaceEmitter`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | U32 |  |
| `unkn1` | U32 |  |

<a id="attr-emitterpriority"></a>
### `EmitterPriority` — TypeID 215

`ReeLib.Efx.Structs.Transforms.EFXAttributeEmitterPriority`

_(no fields)_

<a id="attr-emitterhsv"></a>
### `EmitterHSV` — TypeID 239

`ReeLib.Efx.Structs.Transforms.EFXAttributeEmitterHSV`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Hue` | U32 |  |
| `color` | Color |  |
| `Range1` | RangeI |  |
| `Range2` | RangeI |  |
| `Range3` | RangeI |  |
| `Group1` | Int4 |  |
| `Group2` | Int4 |  |
| `Group3` | Int4 |  |

<a id="attr-emitterhsvexpression"></a>
### `EmitterHSVExpression` — TypeID 240

`ReeLib.Efx.Structs.Transforms.EFXAttributeEmitterHSVExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `16` |
| `emitRate` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn20` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn21` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-pointcloudemitter"></a>
### `PointCloudEmitter` — TypeID 274

`ReeLib.Efx.Structs.Transforms.EFXAttributePointCloudEmitter`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Unkn1` | U32 |  |

## Billboard attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxTypeBillboard.cs`_

<a id="attr-typebillboard2d"></a>
### `TypeBillboard2D` — TypeID 23

`ReeLib.Efx.Structs.Main.EFXAttributeTypeBillboard2D`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `Intensity` | F32 |  |
| `EdgeBlendRange` | F32 |  |
| `AlphaRate` | F32 |  |
| `Rotation` | Range |  |
| `SizeScalar` | Range |  |
| `SizeX` | Range |  |
| `SizeY` | Range |  |
| `Repeat` | S32 (enum [`Repeat`](#enum-repeat)) |  |

<a id="attr-typebillboard2dexpression"></a>
### `TypeBillboard2DExpression` — TypeID 24

`ReeLib.Efx.Structs.Main.EFXAttributeTypeBillboard2DExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `13` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-typebillboard3d"></a>
### `TypeBillboard3D` — TypeID 25

`ReeLib.Efx.Structs.Main.EFXAttributeTypeBillboard3D`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `Intensity` | F32 |  |
| `AlphaRate` | F32 |  |
| `EdgeBlendRange` | F32 |  |
| `Rotation` | Range |  |
| `SizeScalar` | Range |  |
| `SizeX` | Range |  |
| `SizeY` | Range |  |
| `unknDD2` | F32 |  |
| `ParticleIgnoreScale` | Bool |  |
| `EnableGroupColor` | Bool |  |
| `OcclusionByParticleShadow` | Bool |  |
| `Reserved` | Bool |  |
| `Offset` | Range |  |

<a id="attr-typebillboard3dexpression"></a>
### `TypeBillboard3DExpression` — TypeID 26

`ReeLib.Efx.Structs.Main.EFXAttributeTypeBillboard3DExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `13` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorRange` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alphaRate` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `emissive` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `size` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `sizeRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-typebillboard3dmaterial"></a>
### `TypeBillboard3DMaterial` — TypeID 27

`ReeLib.Efx.Structs.Main.EFXAttributeTypeBillboard3DMaterial`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `Rotation` | Range |  |
| `SizeScalar` | Range |  |
| `SizeX` | Range |  |
| `SizeY` | Range |  |
| `Offset` | Range |  |
| `material` | [`EfxMaterialStructBase`](#struct-efxmaterialstructbase) |  |

<a id="attr-typebillboard3dmaterialclip"></a>
### `TypeBillboard3DMaterialClip` — TypeID 28

`ReeLib.Efx.Structs.Main.EFXAttributeTypeBillboard3DMaterialClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `5` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxMaterialClipData`](#struct-efxmaterialclipdata) |  |

<a id="attr-typebillboard3dmaterialexpression"></a>
### `TypeBillboard3DMaterialExpression` — TypeID 29

`ReeLib.Efx.Structs.Main.EFXAttributeTypeBillboard3DMaterialExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `13` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `size` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `ukn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |
| `ukn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `materialExpressionCount` | U32 |  |
| `materialExpressions` | [`EFXMaterialExpressionList`](#struct-efxmaterialexpressionlist) |  |

<a id="attr-typenodebillboard"></a>
### `TypeNodeBillboard` — TypeID 151

`ReeLib.Efx.Structs.Main.EFXAttributeTypeNodeBillboard`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `BlendType` | U32 |  |
| `Type` | S32 (enum [`NodeBillboardType`](#enum-nodebillboardtype)) |  |
| `MaxParticles` | U32 |  |
| `Area0Position` | Vec3 |  |
| `Area0Size` | Vec3 |  |
| `Area0Color` | Color |  |
| `Area0BlendColor` | Color |  |
| `Area0BlendParam` | Vec3 |  |
| `Area1Position` | Vec3 |  |
| `Area1Size` | Vec3 |  |
| `Area1Color` | Color |  |
| `Area1BlendColor` | Color |  |
| `Area1BlendParam` | Vec3 |  |
| `Area2Position` | Vec3 |  |
| `Area2Size` | Vec3 |  |
| `Area2Color` | Color |  |
| `Area2BlendColor` | Color |  |
| `Area2BlendParam` | Vec3 |  |
| `Area3Position` | Vec3 |  |
| `Area3Size` | Vec3 |  |
| `Area3Color` | Color |  |
| `Area3BlendColor` | Color |  |
| `Area3BlendParam` | Vec3 |  |
| `ParticleRotation` | Range |  |
| `ParticleSize` | Range |  |
| `Stretch` | U32 |  |
| `StretchSize` | Range |  |
| `Speed` | Range |  |
| `IntervalFrame` | RangeI |  |
| `LoopCount` | RangeI |  |
| `alphaRate` | F32 |  |

<a id="attr-typenodebillboardexpression"></a>
### `TypeNodeBillboardExpression` — TypeID 152

`ReeLib.Efx.Structs.Main.EFXAttributeTypeNodeBillboardExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[2] | BitSet → `42` |
| `posX_1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posY_1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posZ_1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeX_1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeY_1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeZ_1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color_1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha_1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posX_2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posY_2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posZ_2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeX_2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeY_2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeZ_2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color_2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha_2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posX_3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posY_3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posZ_3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeX_3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeY_3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeZ_3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color_3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha_3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posX_4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posY_4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posZ_4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeX_4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeY_4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `rangeZ_4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color_4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha_4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn33` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn34` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `sizeUnkn` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `sizeUnknRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scaleUnkn` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scaleUnknRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `speedUnkn` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `speedUnknRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn41` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn42` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-typegpubillboard"></a>
### `TypeGpuBillboard` — TypeID 258

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuBillboard`

| Field | Type | Notes |
|---|---|---|
| `BlendFlags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `Intensity` | F32 |  |
| `EdgeBlendRange` | F32 |  |
| `AlphaRate` | F32 |  |
| `ParticleNum` | U32 |  |
| `Flags` | U32 |  |
| `Rotation` | Range |  |
| `SizeScalar` | Range |  |
| `SizeX` | Range |  |
| `SizeY` | Range |  |
| `Offset` | Vec2 |  |

<a id="attr-typegpubillboardexpression"></a>
### `TypeGpuBillboardExpression` — TypeID 259

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuBillboardExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `14` |
| `colorR` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorG` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorB` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorA` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorRate` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `particleSize` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `particleSizeRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

## Mesh attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxTypeMesh.cs`_

<a id="attr-typemesh"></a>
### `TypeMesh` — TypeID 30

`ReeLib.Efx.Structs.Main.EFXAttributeTypeMeshV2`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Flags2` | U32 |  |
| `WildsUknFloat` | F32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `EmissiveColor` | Color |  |
| `EmissiveRate` | F32 |  |
| `MaxPartsNum` | U32 |  |
| `PartsStartNo` | RangeI |  |
| `PlaySpeed` | Range |  |
| `PlaySpeedCoef` | Range |  |
| `PlayType` | S32 (enum [`PlayType`](#enum-playtype)) |  |
| `PlayOrder` | S32 (enum [`PlayOrder`](#enum-playorder)) |  |
| `RotationOrder` | S32 (enum [`RotationOrder`](#enum-rotationorder)) |  |
| `RotationX` | Range |  |
| `RotationY` | Range |  |
| `RotationZ` | Range |  |
| `ScaleX` | Range |  |
| `ScaleY` | Range |  |
| `ScaleZ` | Range |  |
| `ScaleMultiplier` | Range |  |
| `FrontAxis` | S32 (enum [`AxisXYZ`](#enum-axisxyz)) |  |
| `cbSize` | U32 |  |
| `re4_unkn1` | U32 |  |
| `dd2_unkn1` | F32 |  |
| `texCount` | S32 | StructSize → `texPaths` |
| `dd2_unkn2` | U32 |  |
| `MeshPath` | String |  |
| `MirrorMeshPath` | String |  |
| `MaterialPath` | String |  |
| `propertiesDataSize` | S32 | StructSize → `properties` |
| `properties` | [`MdfProperty`](#struct-mdfproperty)[] |  |
| `texPathBlockLength` | S32 |  |
| `texPaths` | String[] |  |

<a id="attr-typemeshclip"></a>
### `TypeMeshClip` — TypeID 31

`ReeLib.Efx.Structs.Main.EFXAttributeTypeMeshClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `13` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxMaterialClipData`](#struct-efxmaterialclipdata) |  |

<a id="attr-typemeshexpression"></a>
### `TypeMeshExpression` — TypeID 32

`ReeLib.Efx.Structs.Main.EFXAttributeTypeMeshExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `25` |
| `color1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color1Rand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alphaRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn20` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn21` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn22` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn23` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn24` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn25` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |
| `materialExpressionsCount` | S32 | StructSize → `materialExpressions` |
| `materialExpressions` | [`EFXMaterialExpressionList`](#struct-efxmaterialexpressionlist) |  |

<a id="attr-typegpumesh"></a>
### `TypeGpuMesh` — TypeID 266

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuMesh`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `ParticleNum` | U32 |  |
| `uknWilds0` | F32 |  |
| `uknWilds1` | U32 |  |
| `cbSize` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `MaxPartsNum` | U32 |  |
| `PartsStartNo` | RangeI |  |
| `PlaySpeed` | Range |  |
| `PlaySpeedCoef` | Range |  |
| `PlayType` | S32 (enum [`PlayType`](#enum-playtype)) |  |
| `PlayOrder` | S32 (enum [`PlayOrder`](#enum-playorder)) |  |
| `RotationOrder` | S32 (enum [`RotationOrder`](#enum-rotationorder)) |  |
| `RotationX` | Range |  |
| `RotationY` | Range |  |
| `RotationZ` | Range |  |
| `ScaleX` | Range |  |
| `ScaleY` | Range |  |
| `ScaleZ` | Range |  |
| `ScaleMultiplier` | Range |  |
| `OrientDirectionUpVector` | S32 (enum [`AxisXYZ`](#enum-axisxyz)) |  |
| `DirectionSmoothness` | F32 |  |
| `texCount` | S32 | StructSize → `texturePaths` |
| `BufferNum` | U32 |  |
| `MeshPath` | String |  |
| `MirrorMeshPath` | String |  |
| `MaterialPath` | String |  |
| `unknDataSize` | U32 | StructSize → `unknData` |
| `unknData` | U8[] |  |
| `texBlockLength` | S32 |  |
| `texturePaths` | String[] |  |

<a id="attr-typegpumeshclip"></a>
### `TypeGpuMeshClip` — TypeID 267

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuMeshClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `5` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxMaterialClipData`](#struct-efxmaterialclipdata) |  |

<a id="attr-typegpumeshexpression"></a>
### `TypeGpuMeshExpression` — TypeID 268

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuMeshExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `19` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alphaRate` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `size` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `sizeRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |
| `materialPropertyCount` | U32 |  |
| `materialExpressions` | [`EFXMaterialExpressionList`](#struct-efxmaterialexpressionlist) |  |

<a id="attr-typegpumeshtrail"></a>
### `TypeGpuMeshTrail` — TypeID 269

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuMeshTrailV2`

| Field | Type | Notes |
|---|---|---|
| `unknFlags` | U32 |  |
| `unkn1` | U32 |  |
| `Wilds_Ukn1` | F32 |  |
| `Wilds_Ukn2` | U32 |  |
| `unkn2` | U32 |  |
| `color1` | Color |  |
| `color2` | Color |  |
| `unkn5` | F32 |  |
| `unkn6` | U32 |  |
| `unkn7` | U32 |  |
| `unkn8` | U32 |  |
| `unkn9` | F32 |  |
| `unkn10` | F32 |  |
| `unkn11` | F32 |  |
| `unkn12` | ukn_type |  |
| `unkn13` | U32 |  |
| `unkn14` | ukn_type |  |
| `unkn15` | U32 |  |
| `unkn16` | ukn_type |  |
| `unkn17` | ukn_type |  |
| `unkn18` | ukn_type |  |
| `unkn19` | ukn_type |  |
| `unkn20` | ukn_type |  |
| `unkn21` | ukn_type |  |
| `unkn22` | F32 |  |
| `unkn23` | ukn_type |  |
| `unkn24` | F32 |  |
| `unkn25` | ukn_type |  |
| `unkn26` | F32 |  |
| `unkn27` | ukn_type |  |
| `unkn28` | F32 |  |
| `unkn29` | ukn_type |  |
| `unkn30` | U32 |  |
| `unkn31` | F32 |  |
| `Wilds_Ukn3` | U32 |  |
| `Wilds_Ukn4` | U32 |  |
| `Wilds_Ukn5` | U32 |  |
| `Wilds_Ukn6` | F32 |  |
| `texCount` | U32 |  |
| `unkn32` | U32 |  |
| `unkn37` | U32 |  |
| `unkn38` | U32 |  |
| `Wilds_Ukn8` | F32 |  |
| `Wilds_Ukn9` | F32 |  |
| `unkn40` | F32 |  |
| `unkn41` | F32 |  |
| `unkn42` | F32 |  |
| `unkn43` | F32 |  |
| `unkn44` | F32 |  |
| `unkn45` | ukn_type |  |
| `unkn46` | ukn_type |  |
| `unkn47` | F32 |  |
| `unkn48` | F32 |  |
| `unkn49` | F32 |  |
| `unkn50` | F32 |  |
| `unkn51` | F32 |  |
| `unkn52` | F32 |  |
| `unkn53` | F32 |  |
| `Wilds_Ukn10` | F32 |  |
| `Wilds_Ukn11` | ukn_type |  |
| `unkn54` | ukn_type |  |
| `unkn55` | F32 |  |
| `Wilds_Ukn12` | ukn_type |  |
| `Wilds_Ukn13` | U32 |  |
| `Wilds_Ukn14` | U32 |  |
| `unkn56` | ukn_type |  |
| `meshPath` | String |  |
| `unkPath` | String |  |
| `mdfPath` | String |  |
| `propertiesDataSize` | S32 | StructSize → `properties` |
| `properties` | [`MdfProperty`](#struct-mdfproperty)[] |  |
| `texBlockLength` | U32 |  |
| `texPaths` | String[] |  |

<a id="attr-typegpumeshtrailclip"></a>
### `TypeGpuMeshTrailClip` — TypeID 270

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuMeshTrailClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `23` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxMaterialClipData`](#struct-efxmaterialclipdata) |  |

<a id="attr-typegpumeshtrailexpression"></a>
### `TypeGpuMeshTrailExpression` — TypeID 271

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuMeshTrailExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `21` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color1R` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color1G` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color1B` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn20` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn21` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |
| `materialExpressionCount` | S32 |  |
| `materialExpressions` | [`EFXMaterialExpressionList`](#struct-efxmaterialexpressionlist) |  |

## Polygon attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxTypePolygon.cs`_

<a id="attr-typepolygon"></a>
### `TypePolygon` — TypeID 66

`ReeLib.Efx.Structs.Main.EFXAttributeTypePolygon`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `Intensity` | F32 |  |
| `EdgeBlendRange` | F32 |  |
| `AlphaRate` | F32 |  |
| `Flags2` | U32 |  |
| `RotationOrder` | S32 (enum [`RotationOrder`](#enum-rotationorder)) |  |
| `RotationX` | Range |  |
| `RotationY` | Range |  |
| `RotationZ` | Range |  |
| `SizeScalar` | Range |  |
| `Width` | Range |  |
| `Height` | Range |  |
| `Offset` | Range |  |
| `ShadowMultiplier` | F32 |  |
| `OrientDirectionUpVector` | S32 (enum [`AxisXYZ`](#enum-axisxyz)) |  |

<a id="attr-typepolygonclip"></a>
### `TypePolygonClip` — TypeID 67

`ReeLib.Efx.Structs.Main.EFXAttributeTypePolygonClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `9` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-typepolygonexpression"></a>
### `TypePolygonExpression` — TypeID 68

`ReeLib.Efx.Structs.Main.EFXAttributeTypePolygonExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `19` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `emissive` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorStrength` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `scale` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `size` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-typepolygonmaterial"></a>
### `TypePolygonMaterial` — TypeID 69

`ReeLib.Efx.Structs.Main.EFXAttributeTypePolygonMaterial`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `RotationOrder` | S32 (enum [`RotationOrder`](#enum-rotationorder)) |  |
| `RotationX` | Range |  |
| `RotationY` | Range |  |
| `RotationZ` | Range |  |
| `SizeScalar` | Range |  |
| `Width` | Range |  |
| `Height` | Range |  |
| `Offset` | Range |  |
| `material` | [`EfxMaterialStructBase`](#struct-efxmaterialstructbase) |  |

<a id="attr-typepolygontrail"></a>
### `TypePolygonTrail` — TypeID 73

`ReeLib.Efx.Structs.Main.EFXAttributeTypePolygonTrail`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `Intensity` | F32 |  |
| `EdgeBlendRate` | F32 |  |
| `AlphaRate` | F32 |  |
| `re4_unkn` | U32 |  |
| `sb_unkn0` | F32 |  |
| `Axis` | S32 (enum [`AxisType`](#enum-axistype)) |  |
| `Length` | Range |  |
| `StretchDistance` | F32 |  |
| `NumTrailDivision` | U32 |  |
| `NumVerticalDivision` | U32 |  |
| `NumSplineDivision` | U32 |  |
| `IntervalFrame` | U32 |  |
| `HeadColor` | Color |  |
| `Place1` | Color |  |
| `Place2` | Color |  |
| `Place1Ratio` | F32 |  |
| `Place2Ratio` | F32 |  |

<a id="attr-typepolygontrailmaterial"></a>
### `TypePolygonTrailMaterial` — TypeID 75

`ReeLib.Efx.Structs.Main.EFXAttributeTypePolygonTrailMaterial`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `Axis` | S32 (enum [`AxisType`](#enum-axistype)) |  |
| `Length` | Range |  |
| `StretchDistance` | F32 |  |
| `NumTrailDivision` | U32 |  |
| `NumVerticalDivision` | U32 |  |
| `NumSplineDivision` | U32 |  |
| `IntervalFrame` | U32 |  |
| `HeadColor` | Color |  |
| `Place1` | Color |  |
| `Place2` | Color |  |
| `Place1Ratio` | F32 |  |
| `Place2Ratio` | F32 |  |
| `material` | [`EfxMaterialStructBase`](#struct-efxmaterialstructbase) |  |

<a id="attr-typepolygontrailmaterialexpression"></a>
### `TypePolygonTrailMaterialExpression` — TypeID 77

`ReeLib.Efx.Structs.Main.EFXAttributeTypePolygonTrailMaterialExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `7` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `materialExpressionCount` | S32 |  |
| `materialExpressions` | [`EFXMaterialExpressionList`](#struct-efxmaterialexpressionlist) |  |

<a id="attr-typegpupolygon"></a>
### `TypeGpuPolygon` — TypeID 260

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuPolygon`

| Field | Type | Notes |
|---|---|---|
| `BlendFlags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `ColorRate` | F32 |  |
| `Intensity` | F32 |  |
| `EdgeBlendRate` | F32 |  |
| `AlphaRate` | F32 |  |
| `Flags` | U32 |  |
| `ParticleNum` | U32 |  |
| `RotationX` | Range |  |
| `RotationY` | Range |  |
| `RotationZ` | Range |  |
| `SizeScalar` | Range |  |
| `Width` | Range |  |
| `Height` | Range |  |
| `OrientDirectionUpVector` | S32 (enum [`AxisXYZ`](#enum-axisxyz)) |  |

<a id="attr-typegpupolygonexpression"></a>
### `TypeGpuPolygonExpression` — TypeID 261

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuPolygonExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `19` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

## Vortexel (wind/heat) attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxVortexel.cs`_

<a id="attr-ptvortexelwind"></a>
### `PtVortexelWind` — TypeID 203

`ReeLib.Efx.Structs.Vortexel.EFXAttributePtVortexelWind`

| Field | Type | Notes |
|---|---|---|
| `TransitionRate` | Range |  |
| `unkn7` | Range |  |
| `TransitionThreshold` | F32 |  |
| `MaxSpeed` | F32 |  |
| `TransitionWaitFrame` | U32 |  |
| `TransitionBlendFrame` | U32 |  |
| `IsTransitionWaitFramePerParticle` | Bool |  |
| `IsMergeGravity` | Bool |  |

<a id="attr-ptvortexelwindexpression"></a>
### `PtVortexelWindExpression` — TypeID 204

`ReeLib.Efx.Structs.Vortexel.EFXAttributePtVortexelWindExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `4` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-vortexelwindemitter"></a>
### `VortexelWindEmitter` — TypeID 205

`ReeLib.Efx.Structs.Vortexel.EFXAttributeVortexelWindEmitter`

| Field | Type | Notes |
|---|---|---|
| `EmitType` | S32 (enum [`VelocityEmitType`](#enum-velocityemittype)) |  |
| `Shape` | S32 (enum [`VelocityShapeType`](#enum-velocityshapetype)) |  |
| `Direction` | S32 (enum [`VelocityShapeType`](#enum-velocityshapetype)) |  |
| `Attenuation` | S32 (enum [`VelocityAttenuationType`](#enum-velocityattenuationtype)) |  |
| `Axis` | Vec3 |  |
| `Speed` | F32 |  |
| `UseOcclusionRate` | Bool |  |
| `UsePressureRate` | Bool |  |
| `IsOutdoorWind` | Bool |  |
| `AttenuatePressure` | Bool |  |
| `unkn0` | F32 |  |
| `flags` | U32 |  |
| `unkn1` | F32 |  |
| `unkn2` | F32 |  |
| `unkn3` | F32 |  |
| `unkn4` | F32 |  |
| `unkn5` | F32 |  |
| `unkn6` | F32 |  |
| `unkn7` | F32 |  |
| `unkn8` | F32 |  |
| `unkn9` | F32 |  |
| `unkn10` | S16 |  |

<a id="attr-vortexelwindemitterexpression"></a>
### `VortexelWindEmitterExpression` — TypeID 206

`ReeLib.Efx.Structs.Vortexel.EFXAttributeVortexelWindEmitterExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `16` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-vortexelcollider"></a>
### `VortexelCollider` — TypeID 208

`ReeLib.Efx.Structs.Vortexel.EFXAttributeVortexelCollider`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Unkn0` | F32 |  |
| `Unkn1` | F32 |  |
| `Unkn2` | F32 |  |
| `Unkn3` | F32 |  |
| `Unkn4` | F32 |  |
| `Unkn5` | F32 |  |
| `Unkn6` | U32 |  |

<a id="attr-vortexelindoormask"></a>
### `VortexelIndoorMask` — TypeID 210

`ReeLib.Efx.Structs.Vortexel.EFXAttributeVortexelIndoorMask`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Unkn0` | F32 |  |
| `Unkn1` | F32 |  |
| `Unkn2` | F32 |  |
| `Unkn3` | F32 |  |
| `Unkn4` | F32 |  |

<a id="attr-ptvortexelphysics"></a>
### `PtVortexelPhysics` — TypeID 212

`ReeLib.Efx.Structs.Vortexel.EFXAttributePtVortexelPhysics`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Shape` | S32 (enum [`SolidBodyShapeType`](#enum-solidbodyshapetype)) |  |
| `Size` | Vec3 |  |
| `BounceRate` | Range |  |
| `Friction` | Range |  |
| `MassDensity` | F32 |  |
| `MomentBias` | F32 |  |
| `PenaltyKinetic` | F32 |  |
| `RotationX` | Range |  |
| `RotationY` | Range |  |
| `RotationZ` | Range |  |
| `InitAngularVelocityX` | Range |  |
| `InitAngularVelocityY` | Range |  |
| `InitAngularVelocityZ` | Range |  |
| `AngularVelocityCoef` | Range |  |

<a id="attr-ptvortexelphysicssimple"></a>
### `PtVortexelPhysicsSimple` — TypeID 213

`ReeLib.Efx.Structs.Vortexel.EFXAttributePtVortexelPhysicsSimple`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `HorizontalBounceRate` | Range |  |
| `VerticalBounceRate` | Range |  |
| `Radius` | F32 |  |

<a id="attr-ptvortexelsnap"></a>
### `PtVortexelSnap` — TypeID 214

`ReeLib.Efx.Structs.Vortexel.EFXAttributePtVortexelSnap`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `RayDistance` | F32 |  |
| `RayStartOffset` | F32 |  |
| `RayHitOffset` | F32 |  |
| `FinishAngleMin` | F32 |  |
| `FinishAngleMax` | F32 |  |

## Lightning attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxTypeLightning.cs`_

<a id="attr-typelightning3d"></a>
### `TypeLightning3D` — TypeID 119

`ReeLib.Efx.Structs.Main.EFXAttributeTypeLightning3D`

| Field | Type | Notes |
|---|---|---|
| `unknBitFlag` | U32 |  |
| `color0` | Color |  |
| `color1` | Color |  |
| `unkn2_0` | F32 |  |
| `unkn2_1` | F32 |  |
| `unkn2_2` | ukn_type |  |
| `unkn2_3` | F32 |  |
| `sb_unkn1` | [`ByteSet`](#struct-byteset) |  |
| `unkn2_4` | F32 |  |
| `unkn2_5` | F32 |  |
| `unkn2_6` | F32 |  |
| `unkn2_7` | F32 |  |
| `unkn2_8` | F32 |  |
| `unkn2_9` | F32 |  |
| `unkn2_10` | F32 |  |
| `unkn2_11` | U32 |  |
| `unkn2_12` | U32 |  |
| `unkn2_13` | U32 |  |
| `unkn2_14` | U32 |  |
| `unkn2_15` | U32 |  |
| `unkn2_16` | F32 |  |
| `unkn2_17` | F32 |  |
| `unkn2_18` | F32 |  |
| `unkn2_19` | F32 |  |
| `unkn2_20` | F32 |  |
| `unkn2_21` | F32 |  |
| `unkn2_22` | F32 |  |
| `unkn2_23` | F32 |  |
| `unkn2_24` | F32 |  |
| `unkn2_25` | F32 |  |
| `unkn2_26` | F32 |  |
| `unkn2_27` | F32 |  |
| `unkn2_28` | F32 |  |
| `unkn2_29` | F32 |  |
| `unkn2_30` | F32 |  |
| `unkn2_31` | F32 |  |
| `unkn2_32` | F32 |  |
| `unkn2_33` | F32 |  |
| `unkn2_34` | F32 |  |
| `unkn2_35` | F32 |  |
| `unkn2_36` | F32 |  |
| `unkn2_37` | F32 |  |
| `unkn2_38` | F32 |  |
| `unkn2_39` | F32 |  |
| `unkn2_40` | F32 |  |
| `unkn2_41` | F32 |  |
| `unkn2_42` | F32 |  |
| `unkn2_43` | F32 |  |
| `unkn2_44` | F32 |  |
| `unkn2_45` | F32 |  |
| `unkn2_46` | F32 |  |
| `unkn2_47` | F32 |  |
| `unkn2_48` | U32 |  |
| `unkn2_49` | U32 |  |
| `unkn2_50` | F32 |  |
| `unkn2_51` | F32 |  |
| `unkn2_52` | F32 |  |
| `unkn2_53` | F32 |  |
| `unkn2_54` | F32 |  |
| `unkn2_55` | F32 |  |
| `unkn2_56` | F32 |  |
| `unkn2_57` | F32 |  |
| `unkn2_58` | F32 |  |
| `unkn2_59` | F32 |  |
| `unkn2_60` | F32 |  |
| `unkn2_61` | F32 |  |
| `unkn2_62` | F32 |  |
| `unkn2_63` | F32 |  |
| `dd2_unkn` | F32 |  |
| `unkn2_64` | U32 |  |
| `unkn2_65` | U32 |  |
| `unkn2_66` | U32 |  |
| `unkn2_67` | F32 |  |
| `unkn2_68` | F32 |  |
| `unkn2_69` | F32 |  |
| `unkn2_70` | U32 |  |
| `unkn2_71` | F32 |  |
| `unkn2_72` | F32 |  |
| `boneName` | String |  |

<a id="attr-typelightning3dexpression"></a>
### `TypeLightning3DExpression` — TypeID 120

`ReeLib.Efx.Structs.Main.EFXAttributeTypeLightning3DExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[2] | BitSet → `48` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `terminalPosX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `terminalPosY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `terminalPosZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn20` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn21` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn22` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn23` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn24` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn25` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn26` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn27` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn28` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn29` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn30` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn31` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn32` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn33` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn34` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn35` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn36` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn37` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn38` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn39` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn40` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn41` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn42` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn43` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn44` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn45` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn46` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn47` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn48` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-typelightning3dmaterial"></a>
### `TypeLightning3DMaterial` — TypeID 121

`ReeLib.Efx.Structs.Main.EFXAttributeTypeLightning3DMaterial`

| Field | Type | Notes |
|---|---|---|
| `unknBitFlag` | U32 |  |
| `color0` | Color |  |
| `color1` | Color |  |
| `unkn2_0` | F32 |  |
| `unkn2_1` | F32 |  |
| `unkn2_2` | F32 |  |
| `unkn2_3` | ukn_type |  |
| `sb_unkn0` | F32 |  |
| `unkn2_4` | F32 |  |
| `unkn2_5` | U32 |  |
| `unkn2_6` | U32 |  |
| `unkn2_7` | U32 |  |
| `unkn2_8` | U32 |  |
| `unkn2_9` | U32 |  |
| `unkn2_10` | F32 |  |
| `unkn2_11` | F32 |  |
| `unkn2_12` | F32 |  |
| `unkn2_13` | F32 |  |
| `unkn2_14` | F32 |  |
| `unkn2_15` | ukn_type |  |
| `unkn2_16` | F32 |  |
| `unkn2_17` | F32 |  |
| `unkn2_18` | F32 |  |
| `unkn2_19` | F32 |  |
| `unkn2_20` | F32 |  |
| `unkn2_21` | ukn_type |  |
| `unkn2_22` | F32 |  |
| `unkn2_23` | ukn_type |  |
| `unkn2_24` | F32 |  |
| `unkn2_25` | ukn_type |  |
| `unkn2_26` | F32 |  |
| `unkn2_27` | ukn_type |  |
| `unkn2_28` | F32 |  |
| `unkn2_29` | ukn_type |  |
| `unkn2_30` | F32 |  |
| `unkn2_31` | ukn_type |  |
| `unkn2_32` | F32 |  |
| `unkn2_33` | ukn_type |  |
| `unkn2_34` | F32 |  |
| `unkn2_35` | F32 |  |
| `unkn2_36` | ukn_type |  |
| `unkn2_37` | F32 |  |
| `unkn2_38` | ukn_type |  |
| `unkn2_39` | F32 |  |
| `unkn2_40` | ukn_type |  |
| `unkn2_41` | F32 |  |
| `unkn2_42` | ukn_type |  |
| `dd2_extra1` | U32 |  |
| `unkn2_43` | ukn_type |  |
| `unkn2_44` | F32 |  |
| `unkn2_45` | ukn_type |  |
| `unkn2_46` | F32 |  |
| `unkn2_47` | ukn_type |  |
| `unkn2_48` | F32 |  |
| `unkn2_49` | F32 |  |
| `unkn2_50` | F32 |  |
| `unkn2_51` | F32 |  |
| `unkn2_52` | F32 |  |
| `unkn2_53` | F32 |  |
| `unkn2_54` | F32 |  |
| `unkn2_55` | F32 |  |
| `unkn2_56` | F32 |  |
| `unkn2_57` | F32 |  |
| `unkn2_58` | U32 |  |
| `unkn2_59` | ukn_type |  |
| `unkn2_60` | ukn_type |  |
| `unkn2_61` | F32 |  |
| `unkn2_62` | F32 |  |
| `unkn2_63` | ukn_type |  |
| `unkn2_64` | U32 |  |
| `unkn2_65` | F32 |  |
| `unkn2_66` | F32 |  |
| `material` | [`EfxMaterialStructBase`](#struct-efxmaterialstructbase) |  |
| `uknString` | String |  |

<a id="attr-typelightning3dmaterialclip"></a>
### `TypeLightning3DMaterialClip` — TypeID 122

`ReeLib.Efx.Structs.Main.EFXAttributeTypeLightning3DMaterialClip`

| Field | Type | Notes |
|---|---|---|
| `ukn1` | U32 |  |
| `ukn2` | U32 |  |
| `ukn3` | U32 |  |
| `ukn4` | F32 |  |
| `ukn5` | U32 |  |
| `ukn6` | U32 |  |
| `ukn7` | ukn_type |  |
| `ukn8` | U32 |  |
| `subSize1` | U32 |  |
| `ukn9` | ukn_type |  |
| `ukn10` | U32 |  |
| `subSize2` | U32 |  |
| `sub1` | S32[] |  |
| `sub2` | S32[] |  |
| `sub3` | S32[] |  |
| `sub4` | S32[] |  |

<a id="attr-typelightning3dmaterialexpression"></a>
### `TypeLightning3DMaterialExpression` — TypeID 123

`ReeLib.Efx.Structs.Main.EFXAttributeTypeLightning3DMaterialExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[2] | BitSet → `44` |
| `terminalPosX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `terminalPosY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `terminalPosZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn20` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn21` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn22` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn23` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn24` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn25` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn26` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn27` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn28` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn29` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn30` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn31` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn32` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn33` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn34` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn35` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn36` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn37` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn38` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn39` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn40` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn41` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn42` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn43` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |
| `unkn44` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `materialExpressionCount` | U32 |  |
| `materialExpressions` | [`EFXMaterialExpressionList`](#struct-efxmaterialexpressionlist) |  |

<a id="attr-typelightningexpensive"></a>
### `TypeLightningExpensive` — TypeID 124

`ReeLib.Efx.Structs.Main.EFXAttributeTypeLightningExpensive`

| Field | Type | Notes |
|---|---|---|
| `data` | U32[46] |  |

<a id="attr-ptlightningbranchaction"></a>
### `PtLightningBranchAction` — TypeID 126

`ReeLib.Efx.Structs.Main.EFXAttributePtLightningBranchAction`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | U32 |  |
| `unkn1` | F32 |  |
| `unkn2` | F32 |  |
| `unkn3` | U32 |  |
| `unkn4` | U32 |  |
| `unkn5` | F32 |  |
| `unkn6` | U32 |  |

<a id="attr-typegpulightning3d"></a>
### `TypeGpuLightning3D` — TypeID 272

`ReeLib.Efx.Structs.Main.EFXAttributeTypeGpuLightning3D`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | U32 |  |
| `color1` | Color |  |
| `color2` | Color |  |
| `unkn1` | F32 |  |
| `unkn2` | ukn_type |  |
| `unkn3` | ukn_type |  |
| `unkn4` | F32 |  |
| `unkn5` | F32 |  |
| `unkn6` | U32 |  |
| `unkn7` | U32 |  |
| `unkn8` | F32 |  |
| `unkn9` | F32 |  |
| `unkn10` | F32 |  |
| `unkn11` | F32 |  |
| `unkn12` | F32 |  |
| `unkn13` | F32 |  |
| `unkn14` | F32 |  |
| `unkn15` | F32 |  |
| `unkn16` | F32 |  |
| `unkn17` | F32 |  |
| `unkn18` | F32 |  |
| `unkn19` | F32 |  |
| `unkn20` | F32 |  |
| `unkn21` | F32 |  |
| `unkn22` | ukn_type |  |
| `unkn23` | F32 |  |
| `unkn24` | ukn_type |  |
| `unkn25` | ukn_type |  |
| `unkn26` | F32 |  |
| `unkn27` | ukn_type |  |
| `unkn28` | ukn_type |  |
| `unkn29` | F32 |  |
| `unkn30` | ukn_type |  |
| `unkn31` | F32 |  |
| `unkn32` | F32 |  |
| `unkn33` | F32 |  |
| `unkn34` | ukn_type |  |
| `unkn35` | F32 |  |
| `unkn36` | F32 |  |
| `unkn37` | F32 |  |
| `unkn38` | U32 |  |
| `unkn39` | U32 |  |
| `unkn40` | F32 |  |
| `unkn41` | F32 |  |
| `unkn42` | U32 |  |
| `unkn2_1` | F32 |  |
| `unkn2_2` | F32 |  |
| `unkn2_3` | F32 |  |
| `unkn2_4` | F32 |  |
| `unkn2_5` | F32 |  |
| `unkn2_6` | F32 |  |
| `unkn2_7` | U32 |  |
| `unkn2_8` | U32 |  |
| `unkn2_9` | U32 |  |
| `unkn2_10` | U32 |  |
| `unkn2_11` | U32 |  |
| `unkn2_12` | U32 |  |
| `unkn2_13` | U32 |  |
| `unkn3_1` | F32 |  |
| `unkn3_2` | F32 |  |
| `unkn3_3` | F32 |  |
| `unkn3_4` | F32 |  |
| `unkn3_5` | F32 |  |
| `unkn3_6` | F32 |  |
| `unkn3_7` | U32 |  |
| `unkn3_8` | U32 |  |
| `unkn3_9` | U32 |  |
| `unkn3_10` | U32 |  |
| `unkn3_11` | U32 |  |
| `unkn3_12` | U32 |  |
| `unkn3_13` | U32 |  |
| `unkn4_1` | F32 |  |
| `unkn4_2` | F32 |  |
| `unkn4_3` | F32 |  |
| `unkn4_4` | F32 |  |
| `unkn4_5` | F32 |  |
| `unkn4_6` | F32 |  |
| `unkn4_7` | U32 |  |
| `unkn4_8` | U32 |  |
| `unkn4_9` | U32 |  |
| `unkn4_10` | U32 |  |
| `unkn4_11` | U32 |  |
| `unkn4_12` | U32 |  |
| `unkn4_13` | U32 |  |
| `str1Len` | U32 |  |
| `str2Len` | U32 |  |
| `str3Len` | U32 |  |
| `str1` | String |  |
| `str2` | String |  |
| `str3` | String |  |

## Fade attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxFade.cs`_

<a id="attr-fadebyangle"></a>
### `FadeByAngle` — TypeID 140

`ReeLib.Efx.Structs.Transforms.EFXAttributeFadeByAngle`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Cone` | F32 |  |
| `Spread` | F32 |  |
| `AlphaRate` | F32 |  |
| `ConeDirection` | Vec3 |  |

<a id="attr-fadebyangleexpression"></a>
### `FadeByAngleExpression` — TypeID 141

`ReeLib.Efx.Structs.Transforms.EFXAttributeFadeByAngleExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `2` |
| `minAngle` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `maxAngle` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-fadebyemitterangle"></a>
### `FadeByEmitterAngle` — TypeID 142

`ReeLib.Efx.Structs.Transforms.EFXAttributeFadeByEmitterAngle`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Cone` | F32 |  |
| `Spread` | F32 |  |
| `AlphaRate` | F32 |  |
| `FadeInStart` | F32 |  |
| `FadeInEnd` | F32 |  |
| `FadeBlend` | U32 |  |

<a id="attr-fadebydepth"></a>
### `FadeByDepth` — TypeID 143

`ReeLib.Efx.Structs.Transforms.EFXAttributeFadeByDepth`

| Field | Type | Notes |
|---|---|---|
| `NearStart` | F32 |  |
| `NearEnd` | F32 |  |
| `FarStart` | F32 |  |
| `FarEnd` | F32 |  |

<a id="attr-fadebydepthexpression"></a>
### `FadeByDepthExpression` — TypeID 144

`ReeLib.Efx.Structs.Transforms.EFXAttributeFadeByDepthExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `4` |
| `nearStart` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `nearEnd` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `farStart` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `farEnd` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-fadebyocclusion"></a>
### `FadeByOcclusion` — TypeID 145

`ReeLib.Efx.Structs.Transforms.EFXAttributeFadeByOcclusion`

| Field | Type | Notes |
|---|---|---|
| `Radius` | F32 |  |
| `Offset` | Vec2 |  |
| `MinSize` | F32 |  |

<a id="attr-fadebyrootculling"></a>
### `FadeByRootCulling` — TypeID 147

`ReeLib.Efx.Structs.Transforms.EFXAttributeFadeByRootCulling`

| Field | Type | Notes |
|---|---|---|
| `ShapeType` | S32 (enum [`EffectBoundsType`](#enum-effectboundstype)) |  |
| `Center` | Vec3 |  |
| `InnerRadius` | F32 |  |
| `OuterRadius` | F32 |  |
| `InnerSize` | Vec3 |  |
| `OuterSize` | Vec3 |  |
| `LocalRotation` | Vec3 |  |
| `RotationOrder` | S32 (enum [`RotationOrder`](#enum-rotationorder)) |  |

## Fluid attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxFluid.cs`_

<a id="attr-fluidemitter2d"></a>
### `FluidEmitter2D` — TypeID 153

`ReeLib.Efx.Structs.Fluid.EFXAttributeFluidEmitter2D`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | U32 |  |
| `dd2_unkn0` | U32 |  |
| `unkn1` | F32 |  |
| `unkn2` | F32 |  |
| `unkn3` | F32 |  |
| `unkn4` | F32 |  |
| `unkn5` | F32 |  |
| `unkn6` | F32 |  |
| `unkn7` | F32 |  |
| `unkn8` | F32 |  |
| `unkn9` | F32 |  |
| `unkn10` | F32 |  |
| `unkn11` | F32 |  |

<a id="attr-fluidemitter2dexpression"></a>
### `FluidEmitter2DExpression` — TypeID 155

`ReeLib.Efx.Structs.Fluid.EFXAttributeFluidEmitter2DExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `2` |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-fluidsimulator2d"></a>
### `FluidSimulator2D` — TypeID 156

`ReeLib.Efx.Structs.Fluid.EFXAttributeFluidSimulator2D`

| Field | Type | Notes |
|---|---|---|
| `unkn0_1` | U8 |  |
| `unkn0_2` | U8 |  |
| `unkn0_3` | U8 |  |
| `unkn0_4` | U8 |  |
| `unkn1` | U32 |  |
| `unkn2` | U32 |  |
| `unkn3` | U32 |  |
| `unkn4` | U32 |  |
| `unkn5` | F32 |  |
| `unkn6` | F32 |  |
| `unkn7` | F32 |  |
| `unkn8` | F32 |  |
| `unkn9` | U32 |  |
| `unkn10` | U32 |  |
| `unkn11` | U32 |  |
| `unkn12` | U32 |  |
| `unkn13` | F32 |  |
| `unkn14` | F32 |  |
| `unkn15` | F32 |  |
| `unkn16` | F32 |  |
| `unkn17` | F32 |  |
| `unkn18` | F32 |  |
| `unkn19` | U32 |  |
| `unkn20` | U32 |  |
| `unkn21` | U32 |  |
| `unkn22` | U32 |  |
| `re4_unkn1` | F32 |  |
| `re4_unkn2` | F32 |  |
| `unkn1_23` | F32 |  |
| `unkn1_24` | F32 |  |
| `unkn1_25` | F32 |  |
| `unkn1_26` | F32 |  |
| `unkn1_27` | F32 |  |
| `unkn1_28_re8` | F32 |  |
| `unkn1_29_re8` | F32 |  |
| `unkn1_30` | F32 |  |
| `unkn1_31` | F32 |  |
| `unkn1_32` | F32 |  |
| `unkn1_33` | F32 |  |
| `unkn1_34_v2` | U32 |  |
| `unkn1_35` | F32 |  |
| `re4_unk2_0` | F32 |  |
| `re4_unk2_1` | F32 |  |
| `re4_unk2_2` | F32 |  |
| `re4_unk2_3` | F32 |  |
| `re4_unk2_4` | F32 |  |
| `re4_unk2_5` | F32 |  |
| `re4_unk2_6` | F32 |  |
| `re4_unk2_7` | F32 |  |
| `re4_unk2_8` | F32 |  |
| `re4_unk2_9` | F32 |  |
| `re4_unk2_10` | F32 |  |
| `unkn1_36_v2` | F32 |  |
| `unkn1_37` | F32 |  |
| `unkn1_38` | F32 |  |
| `unkn1_39_re8` | F32 |  |
| `unkn1_40` | F32 |  |
| `unkn1_42_re8` | S32 |  |
| `dd2_unk1` | F32 |  |
| `dd2_unk2` | U32 |  |
| `unkn2_1` | U32 |  |
| `unkn2_2` | U32 |  |
| `re4_unk3_1` | F32 |  |
| `re4_unk3_2` | F32 |  |
| `re4_unk3_3` | U32 |  |
| `extraByteCount` | U32 |  |
| `path1Size` | U32 |  |
| `path2Size` | U32 |  |
| `path3Size` | U32 |  |
| `path4Size` | U32 |  |
| `path5Size` | U32 |  |
| `uvsPath1` | String |  |
| `uvsPath2` | String |  |
| `uvsPath3` | String |  |
| `uvsPath4` | String |  |
| `uvsPath5` | String |  |
| `extraBytes` | U8[] |  |
| `gradient` | [`FloatWithColor`](#struct-floatwithcolor)[] |  |

<a id="attr-fluidparticle2dsimulator"></a>
### `FluidParticle2DSimulator` — TypeID 157

`ReeLib.Efx.Structs.Fluid.EFXAttributeFluidParticle2DSimulator`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `unkn1` | U32 |  |
| `unkn2` | U32 |  |
| `unkn3` | U32 |  |
| `unkn4` | U32 |  |
| `unkn5` | F32 |  |
| `unkn6` | ukn_type |  |
| `unkn7` | F32 |  |
| `unkn8` | F32 |  |
| `unkn9` | ukn_type |  |
| `unkn10` | ukn_type |  |
| `unkn11` | F32 |  |
| `unkn12` | F32 |  |
| `unkn13` | ukn_type |  |
| `unkn14` | F32 |  |
| `unkn15` | F32 |  |
| `unkn16` | F32 |  |
| `unkn17` | F32 |  |
| `unkn18` | F32 |  |
| `unkn19` | F32 |  |
| `unkn20` | F32 |  |
| `unkn21` | F32 |  |
| `unkn22` | ukn_type |  |
| `unkn23` | F32 |  |
| `unkn24` | ukn_type |  |
| `unkn25` | F32 |  |
| `unkn26` | ukn_type |  |
| `unkn27` | ukn_type |  |
| `unkn28` | ukn_type |  |
| `unkn29` | ukn_type |  |
| `unkn30` | F32 |  |
| `unkn31` | F32 |  |
| `unkn32` | ukn_type |  |
| `unkn33` | F32 |  |
| `unkn34` | F32 |  |
| `unkn35` | F32 |  |
| `unkn36` | S32 |  |
| `unkn37` | S32 |  |
| `unkn38` | S32 |  |
| `unkn39` | ukn_type |  |
| `unkn40` | ukn_type |  |
| `dataCount` | S32 |  |
| `str1` | String |  |
| `str2` | String |  |
| `str3` | String |  |
| `str4` | String |  |
| `str5` | String |  |
| `data` | [`EFXAttributeFluidParticle2DSimulator+HashValue`](#struct-efxattributefluidparticle2dsimulatorhashvalue)[] |  |

<a id="attr-fluidparticleemitter"></a>
### `FluidParticleEmitter` — TypeID 278

`ReeLib.Efx.Structs.Fluid.EFXAttributeFluidParticleEmitter`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Unkn0` | F32 |  |
| `Unkn1` | F32 |  |
| `Unkn2` | F32 |  |
| `Unkn3` | F32 |  |

<a id="attr-fluidparticleemittertarget"></a>
### `FluidParticleEmitterTarget` — TypeID 279

`ReeLib.Efx.Structs.Fluid.EFXAttributeFluidParticleEmitterTarget`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Unkn1` | U32 |  |
| `Unkn2` | U32 |  |
| `Unkn3` | U32 |  |
| `Unkn4` | U32 |  |
| `UserDataFilePath` | String |  |

## Strain ribbon attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxTypeStrain.cs`_

<a id="attr-typestrainribbonmaterial"></a>
### `TypeStrainRibbonMaterial` — TypeID 54

`ReeLib.Efx.Structs.Main.EFXAttributeTypeStrainRibbonMaterial`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | U32 |  |
| `unkn1` | ukn_type |  |
| `unkn2` | U32 |  |
| `unkn3` | ukn_type |  |
| `unkn4` | ukn_type |  |
| `unkn5` | ukn_type |  |
| `unkn6` | F32 |  |
| `unkn7` | F32 |  |
| `unkn8` | F32 |  |
| `unkn9` | U32 |  |
| `unkn10` | F32 |  |
| `unkn11` | F32 |  |
| `unkn12` | F32 |  |
| `unkn13` | F32 |  |
| `unkn14` | F32 |  |
| `unkn15` | U32 |  |
| `unkn16` | U32 |  |
| `unkn17` | F32 |  |
| `unkn18` | F32 |  |
| `color3` | Color |  |
| `color4` | Color |  |
| `color5` | Color |  |
| `unkn22` | F32 |  |
| `unkn23` | F32 |  |
| `unkn24` | F32 |  |
| `unkn25` | F32 |  |
| `unkn26` | F32 |  |
| `unkn27` | F32 |  |
| `unkn28` | F32 |  |
| `unkn29` | F32 |  |
| `unkn30` | F32 |  |
| `unkn31` | F32 |  |
| `unkn32` | F32 |  |
| `unkn33` | F32 |  |
| `unkn34` | F32 |  |
| `wildsUnkn0` | U32 |  |
| `unkn35` | U32 |  |
| `unkn36` | F32 |  |
| `unkn37` | ukn_type |  |
| `unkn38` | F32 |  |
| `unkn39` | ukn_type |  |
| `unkn40` | F32 |  |
| `unkn41` | F32 |  |
| `unkn42` | F32 |  |
| `wildsUnkn1` | U32 |  |
| `wildsColor1` | Color |  |
| `wildsColor2` | Color |  |
| `unkn43` | F32 |  |
| `wildsUnkn4` | U32 |  |
| `unkn44` | F32 |  |
| `unkn45` | F32 |  |
| `unkn47` | F32 |  |
| `unkn48` | U32 |  |
| `unkn49` | ukn_type |  |
| `unkn50` | ukn_type |  |
| `unkn51` | F32 |  |
| `unkn52` | F32 |  |
| `unkn53` | U32 |  |
| `unkn54` | U32 |  |
| `unkn55` | ukn_type |  |
| `unkn56` | ukn_type |  |
| `unkn57` | F32 |  |
| `unkn58` | F32 |  |
| `unkn59` | F32 |  |
| `unkn60` | ukn_type |  |
| `propName` | String |  |
| `unkn61` | ukn_type |  |
| `unkn62` | Color |  |
| `unkn63` | Color |  |
| `unkn64` | F32 |  |
| `unkn65` | ukn_type |  |
| `unkn66` | ukn_type |  |
| `unkn67` | ukn_type |  |
| `material` | [`EfxMaterialStructBase`](#struct-efxmaterialstructbase) |  |

<a id="attr-typestrainribbonmaterialclip"></a>
### `TypeStrainRibbonMaterialClip` — TypeID 55

`ReeLib.Efx.Structs.Main.EFXAttributeTypeStrainRibbonMaterialClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `1` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxMaterialClipData`](#struct-efxmaterialclipdata) |  |

<a id="attr-typestrainribbonmaterialexpression"></a>
### `TypeStrainRibbonMaterialExpression` — TypeID 56

`ReeLib.Efx.Structs.Main.EFXAttributeTypeStrainRibbonMaterialExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `22` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `terminalPosX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `terminalPosY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `terminalPosZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `color4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn20` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn21` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |
| `materialExpressionCount` | S32 | StructSize → `materialExpressions` |
| `materialExpressions` | [`EFXMaterialExpressionList`](#struct-efxmaterialexpressionlist) |  |

<a id="attr-typestrainribbon"></a>
### `TypeStrainRibbon` — TypeID 117

`ReeLib.Efx.Structs.Main.EFXAttributeTypeStrainRibbonV3`

| Field | Type | Notes |
|---|---|---|
| `unkn0_0` | U32 |  |
| `unkn0_1` | U32 |  |
| `unkn0_2` | U32 |  |
| `unkn0_3` | U32 |  |
| `unkn1_0` | F32 |  |
| `unkn1_1` | F32 |  |
| `unkn1_2` | F32 |  |
| `unkn2` | S32 |  |
| `unkn3_0` | F32 |  |
| `unkn3_1` | F32 |  |
| `unkn3_2` | F32 |  |
| `unkn3_3` | F32 |  |
| `unkn3_4` | F32 |  |
| `unkn3_5` | U32 |  |
| `unkn4_0` | U32 |  |
| `unkn4_1` | F32 |  |
| `unkn4_2` | F32 |  |
| `color0` | Color |  |
| `color1` | Color |  |
| `color2` | Color |  |
| `unkn5_0` | F32 |  |
| `unkn5_1` | F32 |  |
| `unkn5_2` | F32 |  |
| `unkn5_3` | F32 |  |
| `unkn5_4` | F32 |  |
| `unkn5_5` | F32 |  |
| `unkn5_6` | F32 |  |
| `unkn5_7` | F32 |  |
| `unkn5_8` | F32 |  |
| `unkn5_9` | F32 |  |
| `unkn5_10` | F32 |  |
| `unkn5_11` | F32 |  |
| `unkn5_12` | F32 |  |
| `wilds_Ukn1` | U32 |  |
| `wilds_Ukn2` | U32 |  |
| `unkn5_13` | F32 |  |
| `unkn5_14` | F32 |  |
| `unkn5_15` | F32 |  |
| `unkn5_16` | F32 |  |
| `unkn5_17` | F32 |  |
| `unkn5_18` | F32 |  |
| `unkn5_19` | F32 |  |
| `unkn5_20` | F32 |  |
| `wilds_Color1` | Color |  |
| `wilds_Color2` | Color |  |
| `unkn5_21` | F32 |  |
| `unkn5_22` | F32 |  |
| `unkn5_23` | F32 |  |
| `unkn5_24` | U32 |  |
| `unkn5_25` | F32 |  |
| `unkn5_26` | F32 |  |
| `unkn5_27` | F32 |  |
| `unkn5_28` | F32 |  |
| `unkn5_29` | F32 |  |
| `unkn5_30` | F32 |  |
| `unkn5_31` | F32 |  |
| `unkn6` | S32 |  |
| `unkn7_0` | F32 |  |
| `wilds_Ukn2_1` | U32 |  |
| `unkn7_1` | F32 |  |
| `unkn7_2` | F32 |  |
| `unkn7_3` | F32 |  |
| `unkn7_4` | F32 |  |
| `unkn7_5` | F32 |  |
| `wilds_Ukn3_1` | U32 |  |
| `wilds_Ukn3_2` | ukn_type |  |
| `wilds_Ukn3_3` | ukn_type |  |
| `wilds_Ukn3_4` | ukn_type |  |
| `wilds_Ukn3_5` | F32 |  |
| `wilds_Ukn3_6` | F32 |  |
| `wilds_UknLast` | ukn_type |  |
| `boneName` | String |  |

<a id="attr-typestrainribbonexpression"></a>
### `TypeStrainRibbonExpression` — TypeID 118

`ReeLib.Efx.Structs.Main.EFXAttributeTypeStrainRibbonExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `24` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posX` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posY` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `posZ` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn20` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn21` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn22` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn23` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn24` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

## Field attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxFieldTypes.cs`_

<a id="attr-vectorfieldparameter"></a>
### `VectorFieldParameter` — TypeID 183

`ReeLib.Efx.Structs.Field.EFXAttributeVectorFieldParameter`

| Field | Type | Notes |
|---|---|---|
| `Parameter` | Vec3 |  |
| `Lacunarity` | F32 |  |
| `Gain` | F32 |  |
| `Blend` | F32 |  |
| `lfoRange` | F32 |  |
| `lfoTime` | F32 |  |
| `Rotation` | Vec3 |  |
| `Scale` | Vec3 |  |
| `Coefficient` | Range |  |
| `EdgeOffset` | F32 |  |
| `Falloff` | F32 |  |
| `Flags` | U32 |  |
| `FieldIndex` | S32 |  |

<a id="attr-vectorfieldparameterclip"></a>
### `VectorFieldParameterClip` — TypeID 184

`ReeLib.Efx.Structs.Field.EFXAttributeVectorFieldParameterClip`

| Field | Type | Notes |
|---|---|---|
| `clipBits` | U32[1] | BitSet → `13` |
| `unkn1` | U32 |  |
| `clipData` | [`EfxClipData`](#struct-efxclipdata) |  |

<a id="attr-vectorfieldparameterexpression"></a>
### `VectorFieldParameterExpression` — TypeID 185

`ReeLib.Efx.Structs.Field.EFXAttributeVectorFieldParameterExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `20` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn19` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn20` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-globalvectorfield"></a>
### `GlobalVectorField` — TypeID 186

`ReeLib.Efx.Structs.Field.EFXAttributeGlobalVectorField`

| Field | Type | Notes |
|---|---|---|
| `TargetCount` | U32 |  |
| `LocalToGlobalBlend` | F32 |  |
| `VelocityBlend` | F32 |  |
| `Weight` | Vec4 |  |
| `InfluenceFrame` | Vec4 |  |

<a id="attr-directionalfieldparameter"></a>
### `DirectionalFieldParameter` — TypeID 189

`ReeLib.Efx.Structs.Field.EFXAttributeDirectionalFieldParameter`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Speed` | Range |  |
| `SpeedCoef` | Range |  |
| `SourcePointUV` | Vec2 |  |
| `SourceRadius` | Vec2 |  |
| `SinkPointUV` | Vec2 |  |
| `SinkRadius` | Vec2 |  |
| `FieldIndex` | S32 |  |

## General struct attributes

_Source: `vendor/RE-Engine-Lib/REE-Lib/OtherFiles/EFX/EfxTypeGeneralStructs.cs`_

<a id="attr-typenodraw"></a>
### `TypeNoDraw` — TypeID 78

`ReeLib.Efx.Structs.Main.EFXAttributeTypeNoDraw`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Color` | Color |  |
| `ColorRange` | Color |  |
| `RotationOrder` | S32 (enum [`RotationOrder`](#enum-rotationorder)) |  |
| `Rotation` | Vec3 |  |
| `RotationRandom` | Vec3 |  |
| `Size` | Vec3 |  |
| `SizeRandom` | Vec3 |  |
| `unkn14` | F32 |  |
| `unkn15` | F32 |  |

<a id="attr-typenodrawexpression"></a>
### `TypeNoDrawExpression` — TypeID 79

`ReeLib.Efx.Structs.Main.EFXAttributeTypeNoDrawExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `16` |
| `color` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `colorRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alpha` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `alphaRand` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn7` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn11` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn12` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn13` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn14` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn15` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn16` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn17` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn18` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

<a id="attr-unitculling"></a>
### `UnitCulling` — TypeID 134

`ReeLib.Efx.Structs.Main.EFXAttributeUnitCulling`

| Field | Type | Notes |
|---|---|---|
| `Flags` | U32 |  |
| `Center` | Vec3 |  |
| `Size` | Vec3 |  |
| `Rotation` | Vec3 |  |
| `DrawDistance` | F32 |  |

<a id="attr-unitcullingexpression"></a>
### `UnitCullingExpression` — TypeID 135

`ReeLib.Efx.Structs.Main.EFXAttributeUnitCullingExpression`

| Field | Type | Notes |
|---|---|---|
| `expressionBits` | U32[1] | BitSet → `11` |
| `unkn1` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn2` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn3` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn4` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn5` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn6` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `cullingRadius` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn8` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn9` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `unkn10` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `cullingDistance` | S32 (enum [`ExpressionAssignType`](#enum-expressionassigntype)) |  |
| `expressions` | [`EFXExpressionList`](#struct-efxexpressionlist) |  |

## Nested / common structs

Types referenced by attribute fields above (embedded objects/structs, not top-level attributes themselves).

<a id="struct-byteset"></a>
### `ByteSet`

`ReeLib.Efx.Structs.Common.ByteSet`

| Field | Type | Notes |
|---|---|---|
| `b1` | U8 |  |
| `b2` | U8 |  |
| `b3` | U8 |  |
| `b4` | U8 |  |

<a id="struct-efxattributefluidparticle2dsimulatorhashvalue"></a>
### `EFXAttributeFluidParticle2DSimulator+HashValue`

`ReeLib.Efx.Structs.Fluid.EFXAttributeFluidParticle2DSimulator+HashValue`

| Field | Type | Notes |
|---|---|---|
| `Value` | F32 |  |
| `Hash` | U32 |  |

<a id="struct-efxattributeptcollisioninfluenceptcollisioninfluencedata"></a>
### `EFXAttributePtCollisionInfluence+PtCollisionInfluenceData`

`ReeLib.Efx.Structs.Pt.EFXAttributePtCollisionInfluence+PtCollisionInfluenceData`

| Field | Type | Notes |
|---|---|---|
| `Hash` | U32 |  |
| `Influence1` | F32 |  |
| `Influence2` | F32 |  |
| `Influence3` | F32 |  |

<a id="struct-efxattributeptpathtranslateptpathtranslatesubstruct"></a>
### `EFXAttributePtPathTranslate+PtPathTranslateSubstruct`

`ReeLib.Efx.Structs.Pt.EFXAttributePtPathTranslate+PtPathTranslateSubstruct`

| Field | Type | Notes |
|---|---|---|
| `unkn0` | F32 |  |
| `unkn1` | F32 |  |
| `unkn2` | F32 |  |
| `unkn3` | F32 |  |
| `unkn4` | F32 |  |
| `unkn5` | F32 |  |
| `unkn6` | F32 |  |

<a id="struct-efxclipdata"></a>
### `EfxClipData`

`ReeLib.Efx.Structs.Common.EfxClipData`

| Field | Type | Notes |
|---|---|---|
| `loopType` | S32 (enum [`EfxClipPlaybackType`](#enum-efxclipplaybacktype)) |  |
| `clipDuration` | F32 |  |
| `clipCount` | S32 | StructSize → `clips` |
| `frameCount` | S32 | StructSize → `frames` |
| `interpolationDataCount` | S32 | StructSize → `interpolationData` |
| `clipDataSize` | S32 | StructSize → `clips` |
| `frameDataSize` | S32 | StructSize → `frames` |
| `interpolationDataSize` | S32 | StructSize → `interpolationData` |
| `clips` | [`EfxClipHeader`](#struct-efxclipheader)[] |  |
| `frames` | [`EfxClipFrame`](#struct-efxclipframe)[] |  |
| `interpolationData` | [`EfxClipInterpolationTangents`](#struct-efxclipinterpolationtangents)[] |  |

<a id="struct-efxclipframe"></a>
### `EfxClipFrame`

`ReeLib.Efx.Structs.Common.EfxClipFrame`

| Field | Type | Notes |
|---|---|---|
| `frameTime` | F32 |  |
| `type` | S32 (enum [`FrameInterpolationType`](#enum-frameinterpolationtype)) |  |
| `value` | F32 |  |

<a id="struct-efxclipheader"></a>
### `EfxClipHeader`

`ReeLib.Efx.Structs.Common.EfxClipHeader`

| Field | Type | Notes |
|---|---|---|
| `frameCount` | S32 |  |
| `valueType` | S32 (enum [`ClipValueType`](#enum-clipvaluetype)) |  |

<a id="struct-efxclipinterpolationtangents"></a>
### `EfxClipInterpolationTangents`

`ReeLib.Efx.Structs.Common.EfxClipInterpolationTangents`

| Field | Type | Notes |
|---|---|---|
| `out_x` | F32 |  |
| `out_y` | F32 |  |
| `in_x` | F32 |  |
| `in_y` | F32 |  |

<a id="struct-efxexpressiondata"></a>
### `EFXExpressionData`

`ReeLib.Efx.Structs.Common.EFXExpressionData`

| Field | Type | Notes |
|---|---|---|
| `type` | S32 (enum [`ExpressionComponentStorageType`](#enum-expressioncomponentstoragetype)) |  |
| `data` | [`EFXExpressionDataBase`](#struct-efxexpressiondatabase) |  |

<a id="struct-efxexpressiondatabase"></a>
### `EFXExpressionDataBase`

`ReeLib.Efx.Structs.Common.EFXExpressionDataBase`

_(no fields)_

<a id="struct-efxexpressiondatabinaryoperator"></a>
### `EFXExpressionDataBinaryOperator`

`ReeLib.Efx.Structs.Common.EFXExpressionDataBinaryOperator`

| Field | Type | Notes |
|---|---|---|
| `value` | S32 (enum [`BinaryExpressionOperator`](#enum-binaryexpressionoperator)) |  |

<a id="struct-efxexpressiondatafloat"></a>
### `EFXExpressionDataFloat`

`ReeLib.Efx.Structs.Common.EFXExpressionDataFloat`

| Field | Type | Notes |
|---|---|---|
| `value` | F32 |  |

<a id="struct-efxexpressiondatafunction"></a>
### `EFXExpressionDataFunction`

`ReeLib.Efx.Structs.Common.EFXExpressionDataFunction`

| Field | Type | Notes |
|---|---|---|
| `value` | S32 (enum [`EfxExpressionFunction`](#enum-efxexpressionfunction)) |  |

<a id="struct-efxexpressiondataparameterhash"></a>
### `EFXExpressionDataParameterHash`

`ReeLib.Efx.Structs.Common.EFXExpressionDataParameterHash`

| Field | Type | Notes |
|---|---|---|
| `parameterHash` | U32 |  |

<a id="struct-efxexpressiondataunaryoperator"></a>
### `EFXExpressionDataUnaryOperator`

`ReeLib.Efx.Structs.Common.EFXExpressionDataUnaryOperator`

| Field | Type | Notes |
|---|---|---|
| `value` | S32 (enum [`UnaryExpressionOperator`](#enum-unaryexpressionoperator)) |  |

<a id="struct-efxexpressionlist"></a>
### `EFXExpressionList`

`ReeLib.Efx.Structs.Common.EFXExpressionList`

| Field | Type | Notes |
|---|---|---|
| `len_expressions` | S32 | StructSize → `expressions` |
| `expressions` | [`EFXExpressionObject`](#struct-efxexpressionobject)[] |  |

<a id="struct-efxexpressionobject"></a>
### `EFXExpressionObject`

`ReeLib.Efx.Structs.Common.EFXExpressionObject`

| Field | Type | Notes |
|---|---|---|
| `parameterCount` | S32 | StructSize → `parameters` |
| `componentsCount` | S32 | StructSize → `components` |
| `struct3Count` | S32 |  |
| `parameters` | [`EFXExpressionParameterName`](#struct-efxexpressionparametername)[] |  |
| `components` | [`EFXExpressionData`](#struct-efxexpressiondata)[] |  |

<a id="struct-efxexpressionparametername"></a>
### `EFXExpressionParameterName`

`ReeLib.Efx.Structs.Common.EFXExpressionParameterName`

| Field | Type | Notes |
|---|---|---|
| `parameterNameHash` | U32 |  |
| `constantValue` | F32 |  |
| `source` | S32 (enum [`ExpressionParameterSource`](#enum-expressionparametersource)) |  |

<a id="struct-efxmaterialclip_struct4"></a>
### `EfxMaterialClip_Struct4`

`ReeLib.Efx.Structs.Common.EfxMaterialClip_Struct4`

| Field | Type | Notes |
|---|---|---|
| `mdfPropertyHash` | U32 |  |
| `unkn1` | S32 |  |
| `unkn2` | S32 |  |
| `unkn3` | S32 |  |

<a id="struct-efxmaterialclipdata"></a>
### `EfxMaterialClipData`

`ReeLib.Efx.Structs.Common.EfxMaterialClipData`

| Field | Type | Notes |
|---|---|---|
| `loopType` | S32 (enum [`EfxClipPlaybackType`](#enum-efxclipplaybacktype)) |  |
| `clipDuration` | F32 |  |
| `clipCount` | S32 | StructSize → `clips` |
| `frameCount` | S32 | StructSize → `frames` |
| `interpolationDataCount` | S32 | StructSize → `interpolationData` |
| `clipDataSize` | S32 | StructSize → `clips` |
| `frameDataSize` | S32 | StructSize → `frames` |
| `interpolationDataSize` | S32 | StructSize → `interpolationData` |
| `mdfPropertyCount` | S32 | StructSize → `mdfProperties` |
| `indicesCount` | S32 | StructSize → `indices` |
| `clips` | [`EfxClipHeader`](#struct-efxclipheader)[] |  |
| `frames` | [`EfxClipFrame`](#struct-efxclipframe)[] |  |
| `interpolationData` | [`EfxClipInterpolationTangents`](#struct-efxclipinterpolationtangents)[] |  |
| `mdfProperties` | [`EfxMaterialClip_Struct4`](#struct-efxmaterialclip_struct4)[] |  |
| `indices` | U32[] |  |

<a id="struct-efxmaterialexpression"></a>
### `EFXMaterialExpression`

`ReeLib.Efx.Structs.Common.EFXMaterialExpression`

| Field | Type | Notes |
|---|---|---|
| `unkn1` | U32 |  |
| `unkn2` | U32 |  |
| `mdfPropertyHash` | U32 |  |
| `propertyComponentIndex` | U32 |  |
| `unkn5` | ukn_type |  |
| `parameterCount` | S32 | StructSize → `parameters` |
| `componentsCount` | S32 | StructSize → `components` |
| `struct3Count` | S32 |  |
| `parameters` | [`EFXExpressionParameterName`](#struct-efxexpressionparametername)[] |  |
| `components` | [`EFXExpressionData`](#struct-efxexpressiondata)[] |  |

<a id="struct-efxmaterialexpressionlist"></a>
### `EFXMaterialExpressionList`

`ReeLib.Efx.Structs.Common.EFXMaterialExpressionList`

| Field | Type | Notes |
|---|---|---|
| `indexCount` | S32 | StructSize → `indices` |
| `expressions` | [`EFXMaterialExpression`](#struct-efxmaterialexpression)[] |  |
| `indices` | U32[] |  |

<a id="struct-efxmaterialstructbase"></a>
### `EfxMaterialStructBase`

`ReeLib.Efx.Structs.Common.EfxMaterialStructBase`

_(no fields)_

<a id="struct-efxmaterialstructv1"></a>
### `EfxMaterialStructV1`

`ReeLib.Efx.Structs.Common.EfxMaterialStructV1`

| Field | Type | Notes |
|---|---|---|
| `maxPropertyIndex` | S32 |  |
| `ukn1` | S32 |  |
| `propertyCount` | S32 | StructSize → `properties` |
| `texCount` | S32 | StructSize → `texPaths` |
| `ukn2` | S32 |  |
| `mdfPathLength` | S32 | StringLength → `mdfPath` |
| `mmtrPathLength` | S32 | StringLength → `mmtrPath` |
| `texBlockSize` | S32 |  |
| `properties` | [`MdfProperty`](#struct-mdfproperty)[] |  |
| `mdfPath` | String |  |
| `mmtrPath` | String |  |
| `texPaths` | String[] |  |

<a id="struct-efxmaterialstructv2"></a>
### `EfxMaterialStructV2`

`ReeLib.Efx.Structs.Common.EfxMaterialStructV2`

| Field | Type | Notes |
|---|---|---|
| `ukn1` | U32 |  |
| `mhws_unkn` | F32 |  |
| `propertyCount` | S32 | StructSize → `properties` |
| `texCount` | S32 | StructSize → `texPaths` |
| `ukn2` | U32 |  |
| `ukn3` | U32 |  |
| `ukn4` | U32 |  |
| `mdfPath` | String |  |
| `mmtrPath` | String |  |
| `propDataSize` | U32 | StructSize → `properties` |
| `properties` | [`MdfProperty`](#struct-mdfproperty)[] |  |
| `texBlockSize` | S32 |  |
| `texPaths` | String[] |  |

<a id="struct-floatwithcolor"></a>
### `FloatWithColor`

`ReeLib.Efx.Structs.Fluid.FloatWithColor`

| Field | Type | Notes |
|---|---|---|
| `value` | F32 |  |
| `color` | Color |  |

<a id="struct-mdfproperty"></a>
### `MdfProperty`

`ReeLib.Efx.Structs.Common.MdfProperty`

| Field | Type | Notes |
|---|---|---|
| `PropertyNameUTF8Hash` | U32 |  |
| `mdfPropertyIndex` | S32 |  |
| `mdfParameterValueCount` | U16 |  |
| `parameterType` | S16 (enum [`MaterialParameterType`](#enum-materialparametertype)) |  |
| `flags` | S32 |  |
| `rawValue` | U8[16] |  |

<a id="struct-ptbehaviorvariable"></a>
### `PtBehaviorVariable`

`ReeLib.Efx.Structs.Pt.PtBehaviorVariable`

| Field | Type | Notes |
|---|---|---|
| `varSize` | S32 |  |
| `dataType` | S32 (enum [`PtBehaviorPropType`](#enum-ptbehaviorproptype)) |  |
| `variable` | [`PtBehaviorVariableDataBase`](#struct-ptbehaviorvariabledatabase) |  |
| `varHash` | U32 |  |
| `behaviorProperty` | String |  |

<a id="struct-ptbehaviorvariabledatabase"></a>
### `PtBehaviorVariableDataBase`

`ReeLib.Efx.Structs.Pt.PtBehaviorVariableDataBase`

| Field | Type | Notes |
|---|---|---|
| `unkn` | S32 |  |
| `size` | S32 |  |
| `re4_unkn0` | S16 |  |
| `re4_unkn1` | S16 |  |

<a id="struct-ptbehaviorvariabledatacolor"></a>
### `PtBehaviorVariableDataColor`

`ReeLib.Efx.Structs.Pt.PtBehaviorVariableDataColor`

| Field | Type | Notes |
|---|---|---|
| `color` | Color |  |
| `restData` | U8[] |  |

<a id="struct-ptbehaviorvariabledataprefabpath"></a>
### `PtBehaviorVariableDataPrefabPath`

`ReeLib.Efx.Structs.Pt.PtBehaviorVariableDataPrefabPath`

| Field | Type | Notes |
|---|---|---|
| `prefabPath` | String |  |

<a id="struct-ptbehaviorvariabledataprefabunknown"></a>
### `PtBehaviorVariableDataPrefabUnknown`

`ReeLib.Efx.Structs.Pt.PtBehaviorVariableDataPrefabUnknown`

| Field | Type | Notes |
|---|---|---|
| `data` | U8[] |  |

<a id="struct-ptbehaviorvariablefloat"></a>
### `PtBehaviorVariableFloat`

`ReeLib.Efx.Structs.Pt.PtBehaviorVariableFloat`

| Field | Type | Notes |
|---|---|---|
| `value` | F32 |  |
| `restData` | U8[] |  |

<a id="struct-ptbehaviorvariablefloat2"></a>
### `PtBehaviorVariableFloat2`

`ReeLib.Efx.Structs.Pt.PtBehaviorVariableFloat2`

| Field | Type | Notes |
|---|---|---|
| `Vec` | Vec2 |  |
| `restData` | U8[] |  |

<a id="struct-ptbehaviorvariablefloat3"></a>
### `PtBehaviorVariableFloat3`

`ReeLib.Efx.Structs.Pt.PtBehaviorVariableFloat3`

| Field | Type | Notes |
|---|---|---|
| `vec` | Vec3 |  |
| `restData` | U8[] |  |

<a id="struct-ptbehaviorvariableinteger"></a>
### `PtBehaviorVariableInteger`

`ReeLib.Efx.Structs.Pt.PtBehaviorVariableInteger`

| Field | Type | Notes |
|---|---|---|
| `value` | S32 |  |
| `restData` | U8[] |  |

<a id="struct-ptpathtranslatename"></a>
### `PtPathTranslateName`

`ReeLib.Efx.Structs.Pt.PtPathTranslateName`

| Field | Type | Notes |
|---|---|---|
| `name` | String |  |

<a id="struct-textureunitdata"></a>
### `TextureUnitData`

`ReeLib.Efx.Structs.Basic.TextureUnitData`

| Field | Type | Notes |
|---|---|---|
| `unkn1` | U32 |  |
| `color` | Color |  |
| `unkn3` | F32 |  |
| `unkn4` | F32 |  |
| `unkn5` | ukn_type |  |
| `unkn6` | F32 |  |
| `unkn7` | F32 |  |
| `unkn8` | F32 |  |
| `unkn9` | F32 |  |
| `unkn10` | F32 |  |
| `unkn11` | F32 |  |
| `unkn12` | F32 |  |
| `unkn13` | ukn_type |  |
| `unkn14` | F32 |  |
| `unkn15` | ukn_type |  |
| `unkn16` | F32 |  |
| `unkn17` | F32 |  |
| `unkn18` | F32 |  |
| `unkn19` | F32 |  |
| `unkn20` | F32 |  |
| `unkn21` | ukn_type |  |
| `unkn22` | F32 |  |
| `unkn23` | F32 |  |
| `unkn24` | F32 |  |
| `unkn25` | F32 |  |
| `unkn26` | F32 |  |
| `unkn27` | ukn_type |  |
| `unkn28` | F32 |  |
| `unkn29` | ukn_type |  |
| `unkn30` | F32 |  |
| `unkn31` | ukn_type |  |
| `unkn32` | F32 |  |
| `unkn33` | ukn_type |  |
| `unkn34` | U32 |  |
| `unkn35` | U32 |  |
| `unkn36` | ukn_type |  |
| `unkn37` | ukn_type |  |
| `unkn38` | F32 |  |
| `unkn39` | F32 |  |

## Enums

<a id="enum-axistype"></a>
### `AxisType`

`ReeLib.Efx.Enums.AxisType`

| Name | Value |
|---|---|
| `AxisType_PositiveX` | 0 |
| `AxisType_PositiveY` | 1 |
| `AxisType_PositiveZ` | 2 |
| `AxisType_NegativeX` | 3 |
| `AxisType_NegativeY` | 4 |
| `AxisType_NegativeZ` | 5 |

<a id="enum-axisxyz"></a>
### `AxisXYZ`

`ReeLib.Efx.Enums.AxisXYZ`

| Name | Value |
|---|---|
| `AxisXYZ_X` | 0 |
| `AxisXYZ_Y` | 1 |
| `AxisXYZ_Z` | 2 |

<a id="enum-binaryexpressionoperator"></a>
### `BinaryExpressionOperator`

`ReeLib.Efx.Structs.Common.BinaryExpressionOperator`

| Name | Value |
|---|---|
| `Max` | 0 |
| `Add` | 1 |
| `Sub` | 2 |
| `Mul` | 3 |
| `Div` | 4 |
| `Min` | 5 |

<a id="enum-clipvaluetype"></a>
### `ClipValueType`

`ReeLib.Efx.Structs.Common.ClipValueType`

| Name | Value |
|---|---|
| `Int` | 3 |
| `Float` | 5 |

<a id="enum-distortiontype"></a>
### `DistortionType`

`ReeLib.Efx.Structs.Misc.DistortionType`

| Name | Value |
|---|---|
| `Blur` | 0 |
| `Refract` | 1 |
| `BlurTexture` | 2 |

<a id="enum-effectboundstype"></a>
### `EffectBoundsType`

`ReeLib.Efx.Enums.EffectBoundsType`

| Name | Value |
|---|---|
| `EffectBoundsType_None` | 0 |
| `EffectBoundsType_Sphere` | 1 |
| `EffectBoundsType_AABB` | 2 |
| `EffectBoundsType_OBB` | 3 |

<a id="enum-efxclipplaybacktype"></a>
### `EfxClipPlaybackType`

`ReeLib.Efx.Structs.Common.EfxClipPlaybackType`

| Name | Value |
|---|---|
| `Unknown` | 0 |
| `NonLooping` | 2 |
| `Type4` | 4 |
| `Looping` | -1 |

<a id="enum-efxexpressionfunction"></a>
### `EfxExpressionFunction`

`ReeLib.Efx.Structs.Common.EfxExpressionFunction`

| Name | Value |
|---|---|
| `Unary0` | 0 |
| `Unary1` | 1 |
| `Unary2` | 2 |
| `Unary4` | 4 |
| `Unary5` | 5 |
| `Unary6` | 6 |
| `Unary7` | 7 |
| `Unary8` | 8 |
| `Unary9` | 9 |
| `Unary10` | 10 |
| `Lerp` | 15 |
| `InvLerp` | 16 |
| `Clamp` | 17 |

<a id="enum-emittercoloroperator"></a>
### `EmitterColorOperator`

`ReeLib.Efx.Enums.EmitterColorOperator`

| Name | Value |
|---|---|
| `EmitterColorOperator_Overwrite` | 0 |
| `EmitterColorOperator_Multiply` | 1 |

<a id="enum-expressionassigntype"></a>
### `ExpressionAssignType`

`ReeLib.Efx.Structs.Common.ExpressionAssignType`

| Name | Value |
|---|---|
| `Add` | 0 |
| `Subtract` | 1 |
| `Multiply` | 2 |
| `Divide` | 3 |
| `Assign` | 4 |
| `ForceWord` | -1 |

<a id="enum-expressioncomponentstoragetype"></a>
### `ExpressionComponentStorageType`

`ReeLib.Efx.Structs.Common.ExpressionComponentStorageType`

| Name | Value |
|---|---|
| `Float` | 0 |
| `BinaryOperator` | 1 |
| `UnaryOperator` | 2 |
| `Function` | 3 |
| `ParameterHash` | 4 |

<a id="enum-expressionparametersource"></a>
### `ExpressionParameterSource`

`ReeLib.Efx.Structs.Common.ExpressionParameterSource`

| Name | Value |
|---|---|
| `Parameter` | 0 |
| `Constant` | 1 |
| `External` | 2 |
| `Unknown` | -1 |

<a id="enum-finish"></a>
### `Finish`

`ReeLib.Efx.Enums.Finish`

| Name | Value |
|---|---|
| `Finish_None` | 0 |
| `Finish_Kill` | 1 |
| `Finish_Freeze` | 2 |

<a id="enum-frameinterpolationtype"></a>
### `FrameInterpolationType`

`ReeLib.Efx.Structs.Common.FrameInterpolationType`

| Name | Value |
|---|---|
| `Unknown` | 0 |
| `Type1` | 1 |
| `Type2` | 2 |
| `Type3` | 3 |
| `Bezier` | 5 |
| `Type13` | 13 |

<a id="enum-lifetype"></a>
### `LifeType`

`ReeLib.Efx.Enums.LifeType`

| Name | Value |
|---|---|
| `LifeType_None` | 0 |
| `LifeType_AppearOnly` | 1 |
| `LifeType_SyncKeepHold` | 2 |
| `LifeType_KeepHold` | 3 |
| `LifeType_FinishKeep` | 4 |

<a id="enum-luminancebleedsamplingtype"></a>
### `LuminanceBleedSamplingType`

`ReeLib.Efx.Enums.LuminanceBleedSamplingType`

| Name | Value |
|---|---|
| `LuminanceBleedSamplingType_Default` | 0 |
| `LuminanceBleedSamplingType_NoSubpixel` | 1 |

<a id="enum-luminancebleedtype"></a>
### `LuminanceBleedType`

`ReeLib.Efx.Enums.LuminanceBleedType`

| Name | Value |
|---|---|
| `LuminanceBleedType_None` | 0 |
| `LuminanceBleedType_Transparent` | 1 |
| `LuminanceBleedType_PostTransparent` | 2 |

<a id="enum-materialparametertype"></a>
### `MaterialParameterType`

`ReeLib.Efx.Structs.Common.MaterialParameterType`

| Name | Value |
|---|---|
| `None` | 0 |
| `Float` | 1 |
| `Range` | 2 |
| `Texture` | 3 |

<a id="enum-nodebillboardtype"></a>
### `NodeBillboardType`

`ReeLib.Efx.Enums.NodeBillboardType`

| Name | Value |
|---|---|
| `NodeBillboardType_Bezier` | 0 |
| `NodeBillboardType_Spline` | 1 |
| `NodeBillboardType_Num` | 2 |

<a id="enum-playorder"></a>
### `PlayOrder`

`ReeLib.Efx.Enums.PlayOrder`

| Name | Value |
|---|---|
| `PlayOrder_Forward` | 0 |
| `PlayOrder_Reverse` | 1 |
| `PlayOrder_RandomReverse` | 2 |

<a id="enum-playtype"></a>
### `PlayType`

`ReeLib.Efx.Enums.PlayType`

| Name | Value |
|---|---|
| `PlayType_Pause` | 0 |
| `PlayType_Loop` | 1 |
| `PlayType_Finish` | 2 |
| `PlayType_Play` | 3 |

<a id="enum-ptbehaviorproptype"></a>
### `PtBehaviorPropType`

`ReeLib.Efx.Structs.Pt.PtBehaviorPropType`

| Name | Value |
|---|---|
| `PropUint` | 4 |
| `PropFloat` | 9 |
| `PropRange` | 10 |
| `PropFloat3` | 11 |
| `PropInt` | 14 |
| `PropColor` | 15 |
| `PropPrefabpath` | 17 |
| `PropEnum` | 18 |
| `PropFloat2` | 19 |
| `PropWstring` | 21 |

<a id="enum-ptcoloroperator"></a>
### `PtColorOperator`

`ReeLib.Efx.Enums.PtColorOperator`

| Name | Value |
|---|---|
| `PtColorOperator_Overwrite` | 0 |
| `PtColorOperator_Multiply` | 1 |

<a id="enum-repeat"></a>
### `Repeat`

`ReeLib.Efx.Enums.Repeat`

| Name | Value |
|---|---|
| `Repeat_None` | 0 |
| `Repeat_U` | 1 |
| `Repeat_V` | 2 |
| `Repeat_UV` | 3 |

<a id="enum-rotationcorrecttype"></a>
### `RotationCorrectType`

`ReeLib.Efx.Enums.RotationCorrectType`

| Name | Value |
|---|---|
| `RotationCorrectType_None` | 0 |
| `RotationCorrectType_ParallelCamera` | 1 |
| `RotationCorrectType_ParallelCameraAxisY` | 2 |
| `RotationCorrectType_ToCamera` | 3 |
| `RotationCorrectType_ToCameraAxisY` | 4 |

<a id="enum-rotationorder"></a>
### `RotationOrder`

`ReeLib.Efx.Enums.RotationOrder`

| Name | Value |
|---|---|
| `RotationOrder_XYZ` | 0 |
| `RotationOrder_YZX` | 1 |
| `RotationOrder_ZXY` | 2 |
| `RotationOrder_ZYX` | 3 |
| `RotationOrder_YXZ` | 4 |
| `RotationOrder_XZY` | 5 |

<a id="enum-shape2dtype"></a>
### `Shape2DType`

`ReeLib.Efx.Enums.Shape2DType`

| Name | Value |
|---|---|
| `Shape2DType_Square` | 0 |
| `Shape2DType_Circle` | 1 |

<a id="enum-shape3dtype"></a>
### `Shape3DType`

`ReeLib.Efx.Enums.Shape3DType`

| Name | Value |
|---|---|
| `Shape3DType_Box` | 0 |
| `Shape3DType_Sphere` | 1 |
| `Shape3DType_Cylinder` | 2 |

<a id="enum-solidbodyshapetype"></a>
### `SolidBodyShapeType`

`ReeLib.Efx.Enums.SolidBodyShapeType`

| Name | Value |
|---|---|
| `SolidBodyShapeType_Sphere` | 0 |
| `SolidBodyShapeType_Box` | 1 |
| `SolidBodyShapeType_Card` | 2 |
| `SolidBodyShapeType_Tetrahedron` | 3 |
| `SolidBodyShapeType_Capsule` | 4 |

<a id="enum-sorttype"></a>
### `SortType`

`ReeLib.Efx.Enums.SortType`

| Name | Value |
|---|---|
| `SortType_ByPosition` | 0 |
| `SortType_ByAlpha` | 1 |
| `SortType_None` | 2 |

<a id="enum-terrainsnaptype"></a>
### `TerrainSnapType`

`ReeLib.Efx.Enums.TerrainSnapType`

| Name | Value |
|---|---|
| `TerrainSnapType_UnderSnap` | 0 |
| `TerrainSnapType_AlwaysSnap` | 1 |

<a id="enum-unaryexpressionoperator"></a>
### `UnaryExpressionOperator`

`ReeLib.Efx.Structs.Common.UnaryExpressionOperator`

| Name | Value |
|---|---|
| `Negation` | 0 |

<a id="enum-velocityattenuationtype"></a>
### `VelocityAttenuationType`

`ReeLib.Efx.Enums.VelocityAttenuationType`

| Name | Value |
|---|---|
| `VelocityAttenuationType_Unknown` | 0 |

<a id="enum-velocityemittype"></a>
### `VelocityEmitType`

`ReeLib.Efx.Enums.VelocityEmitType`

| Name | Value |
|---|---|
| `VelocityEmitType_Unknown` | 0 |

<a id="enum-velocityshapetype"></a>
### `VelocityShapeType`

`ReeLib.Efx.Enums.VelocityShapeType`

| Name | Value |
|---|---|
| `VelocityShapeType_Unknown` | 0 |

<a id="enum-velocitytype"></a>
### `VelocityType`

`ReeLib.Efx.Enums.VelocityType`

| Name | Value |
|---|---|
| `VelocityType_Direction` | 0 |
| `VelocityType_Normal` | 1 |
| `VelocityType_Radial` | 2 |
| `VelocityType_Spread` | 3 |
| `VelocityType_ScreenSpace` | 4 |
| `VelocityType_Max` | 5 |
