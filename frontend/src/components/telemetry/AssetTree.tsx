import React, { useState, useMemo, useEffect } from 'react';
import {
  ChevronRight,
  ChevronDown,
  Building2,
  Boxes,
  Cpu,
  Zap,
  Sun,
  Activity,
  CheckSquare,
  Square,
  Search,
  Filter,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import { Plant, Asset, Channel } from '../../types';
import { Badge } from '../common/Badge';

export interface AssetTreeProps {
  plants: Plant[];
  assets: Asset[];
  channels: Channel[];
  selectedChannelIds: string[];
  onToggleChannel: (channelId: string) => void;
  onSelectChannels: (channelIds: string[], select: boolean) => void;
  loading?: boolean;
  error?: string | null;
}

interface InternalChannelNode {
  id: string;
  canonicalKey: string;
  sourceName: string;
  metricName: string;
  unit: string;
  channel: Channel;
}

interface InternalInverterNode {
  id: string;
  name: string;
  assetType: string;
  asset: Asset;
  channels: InternalChannelNode[];
}

interface InternalBlockNode {
  id: string;
  name: string;
  inverters: InternalInverterNode[];
}

interface InternalPlantNode {
  id: string;
  name: string;
  blocks: InternalBlockNode[];
}

const getHumanMetricName = (canonicalKey: string, sourceName: string): string => {
  const key = (canonicalKey || '').toLowerCase();
  const src = (sourceName || '').toUpperCase();

  if (key === 'power_ac' || src.includes('AC_POWER') || src.includes('AC POWER')) {
    return 'AC Power';
  }
  if (key === 'power_dc' || src.includes('DC_POWER') || src.includes('DC POWER')) {
    return 'DC Power';
  }
  if (
    key === 'energy_ac_daily' ||
    key === 'daily_yield' ||
    src.includes('DAILY_YIELD') ||
    src.includes('DAILY YIELD')
  ) {
    return 'Daily Energy';
  }
  if (
    key === 'energy_ac_total' ||
    key === 'total_yield' ||
    src.includes('TOTAL_YIELD') ||
    src.includes('TOTAL YIELD')
  ) {
    return 'Total Energy';
  }
  if (key === 'irradiance' || src.includes('IRRADIANCE')) {
    return 'Irradiance';
  }
  if (key.includes('temp') || src.includes('TEMP')) {
    return 'Temperature';
  }

  const raw = canonicalKey || sourceName || 'Signal';
  return raw
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
};

const getMetricIcon = (metricName: string) => {
  if (metricName.includes('AC Power')) return <Zap className="w-3.5 h-3.5 text-amber-500" />;
  if (metricName.includes('DC Power')) return <Sun className="w-3.5 h-3.5 text-amber-600" />;
  if (metricName.includes('Daily Energy') || metricName.includes('Total Energy')) {
    return <Activity className="w-3.5 h-3.5 text-emerald-500" />;
  }
  return <Cpu className="w-3.5 h-3.5 text-sky-500" />;
};

export const AssetTree: React.FC<AssetTreeProps> = ({
  plants,
  assets,
  channels,
  selectedChannelIds,
  onToggleChannel,
  onSelectChannels,
  loading = false,
  error = null,
}) => {
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [expandedNodes, setExpandedNodes] = useState<Record<string, boolean>>({});

  const selectedSet = useMemo(() => new Set(selectedChannelIds), [selectedChannelIds]);

  // Build hierarchical structure: Plant -> Block -> Inverter -> Channel
  const treeData = useMemo<InternalPlantNode[]>(() => {
    if (!plants.length && !assets.length && !channels.length) return [];

    // Map channels by asset_id
    const channelMapByAsset: Record<string, Channel[]> = {};
    channels.forEach((c) => {
      if (!channelMapByAsset[c.asset_id]) {
        channelMapByAsset[c.asset_id] = [];
      }
      channelMapByAsset[c.asset_id].push(c);
    });

    // Helper to format channel node
    const formatChannelNode = (c: Channel): InternalChannelNode => {
      const metricName = getHumanMetricName(c.canonical_key, c.source_name);
      const defaultUnit = metricName.includes('Energy') ? 'kWh' : 'kW';
      return {
        id: c.id,
        canonicalKey: c.canonical_key,
        sourceName: c.source_name,
        metricName,
        unit: c.receive_unit || defaultUnit,
        channel: c,
      };
    };

    // Determine target plants
    const plantList = plants.length > 0 ? plants : [{ id: 'default-plant', name: 'Surya Solar Farm' } as Plant];

    return plantList.map((p) => {
      // Find all assets for this plant
      const plantAssets = assets.filter((a) => a.plant_id === p.id || !a.plant_id || plants.length === 1);

      // Distinguish block assets vs inverter assets
      const blockAssets = plantAssets.filter((a) => a.asset_type === 'block');
      const inverterAssets = plantAssets.filter((a) => a.asset_type !== 'block');

      const blocks: InternalBlockNode[] = [];

      if (blockAssets.length > 0) {
        blockAssets.forEach((b) => {
          const childInverters = inverterAssets.filter((inv) => inv.parent_id === b.id);
          const inverters: InternalInverterNode[] = childInverters.map((inv) => ({
            id: inv.id,
            name: inv.name,
            assetType: inv.asset_type,
            asset: inv,
            channels: (channelMapByAsset[inv.id] || []).map(formatChannelNode),
          }));

          blocks.push({
            id: b.id,
            name: b.name,
            inverters,
          });
        });

        // Unassigned inverters directly under plant
        const unassignedInverters = inverterAssets.filter(
          (inv) => !blockAssets.some((b) => b.id === inv.parent_id)
        );

        if (unassignedInverters.length > 0) {
          blocks.push({
            id: `block-direct-${p.id}`,
            name: 'Block 01 (Main)',
            inverters: unassignedInverters.map((inv) => ({
              id: inv.id,
              name: inv.name,
              assetType: inv.asset_type,
              asset: inv,
              channels: (channelMapByAsset[inv.id] || []).map(formatChannelNode),
            })),
          });
        }
      } else {
        // Group all inverters into a logical Block 01
        blocks.push({
          id: `block-default-${p.id}`,
          name: 'Block 01',
          inverters: inverterAssets.map((inv) => ({
            id: inv.id,
            name: inv.name,
            assetType: inv.asset_type,
            asset: inv,
            channels: (channelMapByAsset[inv.id] || []).map(formatChannelNode),
          })),
        });
      }

      return {
        id: p.id,
        name: p.name,
        blocks,
      };
    });
  }, [plants, assets, channels]);

  // Auto-expand all nodes by default when treeData loads
  useEffect(() => {
    const initialExpanded: Record<string, boolean> = {};
    treeData.forEach((plant) => {
      initialExpanded[plant.id] = true;
      plant.blocks.forEach((block) => {
        initialExpanded[block.id] = true;
        block.inverters.forEach((inv) => {
          initialExpanded[inv.id] = true;
        });
      });
    });
    setExpandedNodes((prev) => ({ ...initialExpanded, ...prev }));
  }, [treeData]);

  const toggleExpand = (id: string) => {
    setExpandedNodes((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  // Filter treeData by search query
  const filteredTreeData = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return treeData;

    return treeData
      .map((plant) => {
        const filteredBlocks = plant.blocks
          .map((block) => {
            const filteredInverters = block.inverters
              .map((inv) => {
                const matchingChannels = inv.channels.filter(
                  (ch) =>
                    ch.metricName.toLowerCase().includes(query) ||
                    ch.canonicalKey.toLowerCase().includes(query) ||
                    ch.sourceName.toLowerCase().includes(query)
                );

                const invMatches = inv.name.toLowerCase().includes(query);

                if (invMatches || matchingChannels.length > 0) {
                  return {
                    ...inv,
                    channels: invMatches ? inv.channels : matchingChannels,
                  };
                }
                return null;
              })
              .filter(Boolean) as InternalInverterNode[];

            const blockMatches = block.name.toLowerCase().includes(query);

            if (blockMatches || filteredInverters.length > 0) {
              return {
                ...block,
                inverters: blockMatches ? block.inverters : filteredInverters,
              };
            }
            return null;
          })
          .filter(Boolean) as InternalBlockNode[];

        const plantMatches = plant.name.toLowerCase().includes(query);

        if (plantMatches || filteredBlocks.length > 0) {
          return {
            ...plant,
            blocks: plantMatches ? plant.blocks : filteredBlocks,
          };
        }
        return null;
      })
      .filter(Boolean) as InternalPlantNode[];
  }, [treeData, searchQuery]);

  if (loading) {
    return (
      <div className="p-6 text-center text-slate-400 font-mono text-xs flex flex-col items-center justify-center gap-2 bg-white rounded-xl border border-slate-200/90 shadow-xs">
        <Loader2 className="w-6 h-6 animate-spin text-sky-600" />
        <span>Loading Asset Tree...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-rose-50 border border-rose-200 text-rose-800 rounded-xl text-xs font-mono flex items-center gap-2">
        <AlertCircle className="w-4 h-4 text-rose-600 flex-shrink-0" />
        <span>Unable to load asset tree: {error}</span>
      </div>
    );
  }

  if (!treeData.length) {
    return (
      <div className="p-6 text-center text-slate-400 font-mono text-xs bg-white rounded-xl border border-slate-200/90 shadow-xs">
        No assets or telemetry channels found.
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200/90 shadow-xs overflow-hidden flex flex-col h-full">
      {/* Search Header */}
      <div className="p-3 border-b border-slate-100 bg-slate-50/60 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-bold text-slate-800 font-mono uppercase tracking-wider flex items-center gap-1.5">
            <Building2 className="w-3.5 h-3.5 text-sky-600" />
            Asset Hierarchy
          </span>
          <Badge variant="blue" size="sm">
            {selectedChannelIds.length} Selected
          </Badge>
        </div>

        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search plant, inverter, signal..."
            className="w-full pl-8 pr-3 py-1.5 text-xs border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-sky-500 bg-white"
          />
        </div>
      </div>

      {/* Tree View Body */}
      <div className="p-2 overflow-y-auto max-h-[520px] space-y-1 text-xs font-mono select-none">
        {filteredTreeData.map((plant) => {
          const isPlantExpanded = expandedNodes[plant.id] !== false;
          const allPlantChannelIds = plant.blocks.flatMap((b) =>
            b.inverters.flatMap((i) => i.channels.map((c) => c.id))
          );
          const isAllPlantSelected =
            allPlantChannelIds.length > 0 &&
            allPlantChannelIds.every((id) => selectedSet.has(id));

          return (
            <div key={plant.id} className="space-y-1">
              {/* Plant Node */}
              <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-md hover:bg-slate-100/80 cursor-pointer font-bold text-slate-900 bg-slate-50 border border-slate-200/60">
                <button
                  type="button"
                  onClick={() => toggleExpand(plant.id)}
                  className="p-0.5 text-slate-500 hover:text-slate-800"
                >
                  {isPlantExpanded ? (
                    <ChevronDown className="w-4 h-4" />
                  ) : (
                    <ChevronRight className="w-4 h-4" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => onSelectChannels(allPlantChannelIds, !isAllPlantSelected)}
                  className="text-slate-500 hover:text-sky-600"
                >
                  {isAllPlantSelected ? (
                    <CheckSquare className="w-4 h-4 text-sky-600" />
                  ) : (
                    <Square className="w-4 h-4 text-slate-300" />
                  )}
                </button>
                <Building2 className="w-4 h-4 text-sky-700" />
                <span className="truncate flex-1">{plant.name}</span>
                <span className="text-[10px] text-slate-400 font-normal">
                  {allPlantChannelIds.length} channels
                </span>
              </div>

              {/* Blocks */}
              {isPlantExpanded && (
                <div className="pl-4 space-y-1 border-l border-slate-200 ml-3">
                  {plant.blocks.map((block) => {
                    const isBlockExpanded = expandedNodes[block.id] !== false;
                    const allBlockChannelIds = block.inverters.flatMap((i) =>
                      i.channels.map((c) => c.id)
                    );
                    const isAllBlockSelected =
                      allBlockChannelIds.length > 0 &&
                      allBlockChannelIds.every((id) => selectedSet.has(id));

                    return (
                      <div key={block.id} className="space-y-1">
                        {/* Block Node */}
                        <div className="flex items-center gap-1.5 px-2 py-1 rounded-md hover:bg-slate-100 cursor-pointer text-slate-800 font-semibold">
                          <button
                            type="button"
                            onClick={() => toggleExpand(block.id)}
                            className="p-0.5 text-slate-400 hover:text-slate-700"
                          >
                            {isBlockExpanded ? (
                              <ChevronDown className="w-3.5 h-3.5" />
                            ) : (
                              <ChevronRight className="w-3.5 h-3.5" />
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={() => onSelectChannels(allBlockChannelIds, !isAllBlockSelected)}
                            className="text-slate-400 hover:text-sky-600"
                          >
                            {isAllBlockSelected ? (
                              <CheckSquare className="w-3.5 h-3.5 text-sky-600" />
                            ) : (
                              <Square className="w-3.5 h-3.5 text-slate-300" />
                            )}
                          </button>
                          <Boxes className="w-3.5 h-3.5 text-emerald-600" />
                          <span className="truncate flex-1">{block.name}</span>
                          <span className="text-[10px] text-slate-400 font-normal">
                            {block.inverters.length} inverters
                          </span>
                        </div>

                        {/* Inverters */}
                        {isBlockExpanded && (
                          <div className="pl-4 space-y-1 border-l border-slate-200 ml-2.5">
                            {block.inverters.map((inv) => {
                              const isInvExpanded = expandedNodes[inv.id] !== false;
                              const invChannelIds = inv.channels.map((c) => c.id);
                              const isAllInvSelected =
                                invChannelIds.length > 0 &&
                                invChannelIds.every((id) => selectedSet.has(id));

                              return (
                                <div key={inv.id} className="space-y-0.5">
                                  {/* Inverter Node */}
                                  <div className="flex items-center gap-1.5 px-2 py-1 rounded-md hover:bg-slate-100 cursor-pointer text-slate-700">
                                    <button
                                      type="button"
                                      onClick={() => toggleExpand(inv.id)}
                                      className="p-0.5 text-slate-400 hover:text-slate-600"
                                    >
                                      {isInvExpanded ? (
                                        <ChevronDown className="w-3 h-3" />
                                      ) : (
                                        <ChevronRight className="w-3 h-3" />
                                      )}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => onSelectChannels(invChannelIds, !isAllInvSelected)}
                                      className="text-slate-400 hover:text-sky-600"
                                    >
                                      {isAllInvSelected ? (
                                        <CheckSquare className="w-3.5 h-3.5 text-sky-600" />
                                      ) : (
                                        <Square className="w-3.5 h-3.5 text-slate-300" />
                                      )}
                                    </button>
                                    <Cpu className="w-3.5 h-3.5 text-amber-500" />
                                    <span className="truncate flex-1 font-medium">{inv.name}</span>
                                  </div>

                                  {/* Channels */}
                                  {isInvExpanded && (
                                    <div className="pl-6 space-y-0.5 border-l border-slate-100 ml-3">
                                      {inv.channels.map((ch) => {
                                        const isSelected = selectedSet.has(ch.id);
                                        return (
                                          <div
                                            key={ch.id}
                                            onClick={() => onToggleChannel(ch.id)}
                                            className={`flex items-center gap-2 px-2 py-1 rounded-md cursor-pointer transition ${
                                              isSelected
                                                ? 'bg-sky-50/90 text-sky-900 border border-sky-200/80 font-semibold'
                                                : 'hover:bg-slate-100/70 text-slate-600'
                                            }`}
                                          >
                                            {isSelected ? (
                                              <CheckSquare className="w-3.5 h-3.5 text-sky-600 flex-shrink-0" />
                                            ) : (
                                              <Square className="w-3.5 h-3.5 text-slate-300 flex-shrink-0" />
                                            )}
                                            {getMetricIcon(ch.metricName)}
                                            <span className="truncate flex-1">{ch.metricName}</span>
                                            <span className="text-[10px] font-mono text-slate-400 uppercase">
                                              {ch.unit}
                                            </span>
                                          </div>
                                        );
                                      })}
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
