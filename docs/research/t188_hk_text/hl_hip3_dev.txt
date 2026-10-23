> For the complete documentation index, see [llms.txt](https://hyperliquid.gitbook.io/hyperliquid-docs/llms.txt). Markdown versions of documentation pages are available by appending `.md` to page URLs; this page is available as [Markdown](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-3-deployer-actions.md).

# HIP-3 deployer actions

The API for deploying and operating builder-deployed perpetual dexs involves the following L1 actions:

```typescript
// IMPORTANT: All lists of tuples should be lexographically sorted before signing
type PerpDeployAction =
  | {
      type: "perpDeploy";
      registerAsset2: RegisterAsset2;
    }
  | {
      type: "perpDeploy";
      registerAsset: RegisterAsset;
    }
  | {
      type: "perpDeploy";
      setOracle: SetOracle;
    }
  | {
      type: "perpDeploy";
      setFundingMultipliers: SetFundingMultipliers;
    }
  | {
      type: "perpDeploy";
      setFundingInterestRates: SetFundingInterestRates;
    }
  | {
      type: "perpDeploy";
      setFundingClamps: SetFundingClamps;
    }
  | {
      type: "perpDeploy";
      haltTrading: { coin: string; isHalted: boolean };
    }
  | {
      type: "perpDeploy";
      insertMarginTable: InsertMarginTable;
    }
  | {
      type: "perpDeploy";
      setMarginTableIds: SetMarginTableIds;
    }
  | {
      type: "perpDeploy";
      setFeeRecipient: { dex: string; feeRecipient: address };
    }
  | {
      type: "perpDeploy";
      setOpenInterestCaps: SetOpenInterestCaps;
    }
  | {
      type: "perpDeploy";
      setSubDeployers: { dex: string; subDeployers: Array<SubDeployerInput> };
    }
  | {
      type: "perpDeploy";
      setMarginModes: SetMarginModes;
    }
  | {
      type: "perpDeploy";
      setDeployerFees: SetDeployerFees;
    }
  | {
      type: "perpDeploy";
      setPerpAnnotation: SetPerpAnnotation;
    }
  | {
      type: "perpDeploy";
      disableDex: string;
    };

// User-signed action to transfer collateral between the user's DEX account and its backstop liquidator.
// ntl must be positive and a multiple of 1_000_000_000.
type Hip3LiquidatorTransferAction = {
  type: "hip3LiquidatorTransfer";
  dex: string;
  ntl: number; // Integer amount in millionths of a collateral token: 1_000_000_000 = 1,000 tokens
  isDeposit: boolean; // true deposits; false withdraws
};

/**
 * RegisterAsset2 can be called to initialize a new dex and register an asset at the same time.
 * If schema is not provided, then RegisterAsset can be called multiple times to register additional assets
 * for the provided dex.
 * @param maxGas - Max gas in native token wei. If not provided, then uses current deploy auction price.
 * If the max gas is 0, then a reserve deployment will be used.
 * A reserve deployment allows deployment at the current price of the gas auction, even if it has ended.
 * Currently, 7 reserve deployments are allowed.
 * IMPORTANT: A reserve deployment will be used regardless of whether the auction has completed, so deployers should query the auction status first.
 * @param assetRequest - Contains new asset listing parameters. See RegisterAssetRequest2 below for details.
 * @param dex - Name of the perp dex (2-4 lowercase characters)
 * @param schema - Contains new perp dex parameters. See PerpDexSchemaInput below for details.
 */
type RegisterAsset2 = {
  maxGas?: number;
  assetRequest: RegisterAssetRequest2;
  dex: string;
  schema?: PerpDexSchemaInput;
};

// Same as RegisterAsset2 but uses RegisterAssetRequest
type RegisterAsset = {
  maxGas?: number;
  assetRequest: RegisterAssetRequest;
  dex: string;
  schema?: PerpDexSchemaInput;
};

type RegisterAssetRequest2 = {
  coin: string;
  szDecimals: number;
  oraclePx: string;
  marginTableId: number;
  marginMode: "strictIsolated" | "noCross" | "normal"; // strictIsolated does not allow withdrawing of isolated margin from open positions
};

type RegisterAssetRequest = {
  coin: string;
  szDecimals: number;
  oraclePx: string;
  marginTableId: number;
  onlyIsolated: boolean;
};

/**
 * The markPxs outer list can be length 0, 1, or 2. The median of these inputs
 * along with the local mark price (median(best bid, best ask, last trade price))
 * is used as the new mark price update.
 *
 * SetOracle can be called multiple times but there must be at least 2.5 seconds between calls.
 *
 * Stale mark prices will be updated to the local mark price after 10 seconds of no updates.
 * This fallback counts as an update for purposes of the maximal update frequency.
 * This fallback behavior should not be relied upon. Deployers are expected to call setOracle every 3 seconds even with no changes.
 *
 * All prices are clamped to 10x the start of day value.
 * markPx moves are clamped to 1% from previous markPx.
 * markPx cannot be updated such that open interest would be 10x the open interest cap.
 * @param dex - Name of the perp dex
 * @param oraclePxs - A list (sorted by key) of asset and oracle prices.
 * @param markPxs - An outer list of inner lists (inner list sorted by key) of asset and mark prices.
 * @param externalPerpPxs - A list (sorted by key) of asset and external prices which prevent sudden mark price deviations.
 * Ideally externally determined by deployer, but could fall back to an EMA of recent mark prices.
 * Must include all assets.
 */
type SetOracle = {
  dex: string;
  oraclePxs: Array<[string, string]>;
  markPxs: Array<Array<[string, string]>>;
  externalPerpPxs: Array<[string, string]>;
};

/**
 * @param fullName - Full name of the perp dex
 * @param collateralToken - Collateral token index
 * @param oracleUpdater - User to update oracles. If not provided, then deployer is assumed to be oracle updater.
 */
type PerpDexSchemaInput = {
  fullName: string;
  collateralToken: int;
  oracleUpdater?: string;
};

/**
 * A sorted list of asset and funding multiplier.
 * Multipliers must be between 0 and 10 and are used to scale the funding rate.
 */
type SetFundingMultipliers = Array<[string, string]>;

/**
 * A sorted list of asset and 8 hour interest rate.
 * Interest rates must be between -0.01 and 0.01 and are used as the interest rate
 * component in the funding calculation.
 */
type SetFundingInterestRates = Array<[string, string]>;

/**
 * A sorted list of asset and 8 hour funding clamp.
 * Clamps must be between 0 and 0.01 and bound how far the funding rate can move away from the
 * average premium toward the interest rate. Defaults to 0.0003.
 */
type SetFundingClamps = Array<[string, string]>;

/**
 * A sorted of asset and margin table ids.
 * Margin table ids must be non-zero.
 */
type SetMarginTableIds = Array<[string, number]>;

/**
 * Inserts margin table to dex
 */
type InsertMarginTable = {
  dex: string;
  marginTable: RawMarginTable;
};

/**
 * marginTiers must be sorted in order of increasing lower bound and decreasing maxLeverage
 * marginTiers has a maximum length of 3.
 */
type RawMarginTable = {
  description: string;
  marginTiers: Array<RawMarginTier>;
};

/**
 * lowerBound is a position notional value above which the leverage is constrained by maxLeverage
 */
type RawMarginTier = {
  lowerBound: int;
  maxLeverage: MaxLeverage;
};

/**
 * Max leverage is in the range [1, 50]
 */
type MaxLeverage = number;

/**
 * A sorted list of asset and open interest cap notionals.
 * Open interest caps must be at least the maximum of 1_000_000 (1 size unit of collateral asset) or half of the current open interest.
 * null removes the custom cap for an asset.
 */
type SetOpenInterestCaps = Array<[string, number | null]>;

/**
 * A modification to sub-deployer permissions
 */
type SubDeployerInput = {
  variant: string; // corresponds to a variant of PerpDeployAction. For example, "haltTrading" or "setOracle"
  user: String;
  allowed: boolean; // add or remove the subDeployer from the authorized set for the action variant
};

// A sorted list of (coin, marginMode). See RegisterAssetRequest2 for margin mode definitions.
type SetMarginModes = Array<[string, "strictIsolated" | "noCross" | "normal"]>;

// Let the user normal rate be `x`. Let the user rate be `y` after accounting for aligned quote collateral.
// In other words, `x = y` for non-aligned collateral.
// User pays or receives rebate `P + D` where `P` goes to protocol and `D` goes to deployer.
// If `x > 0` and `scale < 1`, `P = y` and `D = scale * x`
// If `x > 0` and `scale > 1`, `P = y * scale` and `D = x * scale`
// If `x < 0` and `scale < 1`, `P = y / (1 + scale)` and `D = y * scale / (1 + scale)`
// If `x < 0` and `scale > 1`, `P = y / 2` and `D = y / 2`
// On Mainnet, rate limited to one change per 30 days.
// Note that there are currently no aligned quote assets on mainnet.
type SetDeployerFees = Array<
  [
    string,
    {
      scale: string; // Decimal string in [0.0, 3.0], or [0.0, 10.0) when growthMode is true
      growthMode: boolean;
    },
  ]
>;

// category <= 15 characters
// description <= 400 characters
// displayName <= 9 characters
// <= 2 keywords, each keyword <= 10 characters
type SetPerpAnnotation = {
  coin: string;
  category: string;
  description: string;
  displayName: string | null;
  keywords: Array<string>;
};
```

For the following examples, `feeScale` is the `scale` field in `SetDeployerFees`. Assume a positive normal user fee of 1 unit and non-aligned collateral (`x = y = 1`). `userFeeToProtocol` and `userFeeToDeployer` are the resulting fee units charged to the user.

| `growthMode` | `feeScale` | `userFeeToProtocol` | `userFeeToDeployer` |
| ------------ | ---------- | ------------------- | ------------------- |
| `false`      | `"0"`      | `1`                 | `0`                 |
| `false`      | `"0.5"`    | `1`                 | `0.5`               |
| `false`      | `"1"`      | `1`                 | `1`                 |
| `false`      | `"3"`      | `3`                 | `3`                 |
| `true`       | `"0"`      | `0.1`               | `0`                 |
| `true`       | `"0.5"`    | `0.1`               | `0.05`              |
| `true`       | `"1"`      | `0.1`               | `0.1`               |
| `true`       | `"3.01"`   | `0.301`             | `0.301`             |
| `true`       | `"9.99"`   | `0.999`             | `0.999`             |

See <https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals#retrieve-information-about-the-perp-deploy-auction> for how to query for the perp deploy auction status.

#### Open interest caps

Builder-deployed perp markets are subject to two types of open interest caps: notional (sum of absolute position size times mark price) and size (sum of absolute position sizes).

Notional open interest caps are enforced on the total open interest summed over all assets within the DEX, as well as per-asset. Perp deployers can set a custom open interest cap per asset, which is documented in <https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/hip-3-deployer-actions>.

Size-denominated open interest caps are only enforced per-asset. Size-denominated open interest caps are currently a constant 1B per asset, so a reasonable default would be to set `szDecimals` such that the minimal size increment is $1-10 at the initial mark price.

#### Backstop liquidator

The backstop liquidator address is `0x4000000000000000000000000000000000000000 + {dex_index}`. For example, the first HIP-3 DEX has backstop liquidator address `0x4000000000000000000000000000000000000001`.

#### Node user clearinghouse states

The node flag `--write-user-clearinghouse-states <dex>` writes clearinghouse states for the named HIP-3 DEX to hourly files at `~/hl/data/dex_user_clearinghouse_states/hourly/<date>/<hour>`, where `date` is `YYYYMMDD`. Each line is a JSON array `[time, messages]`, where `time` is the block time and `messages` is either a single snapshot of every user on the DEX or a list of per-user diffs:

```json
["2026-09-24T09:00:00.123", [{ "Snapshot": { "0xUSER_A": <clearinghouseState> } }]]
["2026-09-24T09:00:03.456", [{ "Diff": ["0xUSER_A", <clearinghouseState>] }]]
```

Each `<clearinghouseState>` has the same format as the `clearinghouseState` info request response for that DEX, denominated in the venue's collateral token. It only accounts for the user's state on the named DEX, so collateral shared across DEXes (e.g. through user abstraction) is not included, and `liquidationPx` is always `null`. The first line of each file, and the first line written after the node starts, is a snapshot. Other lines contain diffs for users whose clearinghouse state changed, ignoring `time`: every such user on an oracle update for the venue, or only the users involved in a fill, liquidation, funding payment, or transfer into or out of the venue.

## HIP-3\* (testnet-only)

### Star actions

A HIP-3 venue can be designated HIP-3\* at time of creation by setting `isStar: true` in `PerpDexSchemaInput`. This optional boolean defaults to `false`. HIP-3\* enables several features on top of the HIP-3 spec, including an allow-list and proxied user actions.

#### Operations

```typescript
type Hip3StarAction = {
  type: "perpDeploy";
  star: { dex: string; operation: Hip3StarOperation };
};

type Hip3StarOperation =
  | { proxy: [address, Hip3StarProxyOperation] }
  | { setOracle: { oraclePxs: Array<[string, string]> } };

// CancelAction and OrderAction are the standard exchange actions.
type Hip3StarProxyOperation =
  | { modifyApproval: boolean }
  | { modifyBackstopLiquidatorApproval: boolean }
  | { setReduceOnly: boolean }
  | { cancel: Omit<CancelAction, "type"> }
  | { cancelAll: { assets?: Array<number> | null } }
  | { order: Omit<OrderAction, "type"> }
  | { sendAsset: { destination: address; amount: string } };
```

```json
{
  "type": "perpDeploy",
  "star": {
    "dex": "test",
    "operation": { "proxy": ["0xUSER_A", { "modifyApproval": true }] }
  }
}
{
  "type": "perpDeploy",
  "star": {
    "dex": "test",
    "operation": { "proxy": ["0xUSER_B", { "cancelAll": { "assets": [100001, 100002] } }] }
  }
}
{
  "type": "perpDeploy",
  "star": {
    "dex": "test",
    "operation": { "setOracle": { "oraclePxs": [["test:BTC", "100000.0"], ["test:ETH", "4000.0"]] } }
  }
}
```

* **`proxy`** — a pair of a user address and one proxy operation applied to that user.
* **`setOracle`** — updates oracle prices, as described under Oracle below.

#### Proxy operations

* **`modifyApproval`** — `{ "modifyApproval": true }` adds the user to the allowlist, `false` removes them and clears their flags. Removing a user who is not approved is a no-op. Re-approving an approved user is a no-op and keeps the user's flags. A removed user who is approved again starts with default flags.
* **`modifyBackstopLiquidatorApproval`** — `{ "modifyBackstopLiquidatorApproval": true }` allows the user to deposit into and withdraw from the venue's backstop liquidator via `hip3LiquidatorTransfer`; `false` revokes this. The user must already be approved via `modifyApproval`.
* **`setReduceOnly`** — `{ "setReduceOnly": true }` restricts an approved user to reducing their positions on the venue. The user can only place reduce-only orders and TWAPs, modify orders into reduce-only orders, and cancel. `{ "setReduceOnly": false }` restores full trading.
* **`cancel`** — `{ "cancel": { "cancels": [{ "a": <asset>, "o": <oid> }] } }`, the standard `cancel` exchange-action payload. Cancels the user's resting orders by oid.
* **`cancelAll`** — `{ "cancelAll": { "assets": null } }` cancels all of the user's resting orders and TWAPs on this venue. `{ "cancelAll": { "assets": [<asset>, ...] } }` cancels only the user's resting orders and TWAPs for the listed assets. The list must contain 1-10 entries.
* **`order`** — `{ "order": { "orders": [...], "grouping": "na" } }`, the standard `order` exchange-action payload. Every order must be reduce-only (`"r": true`).
* **`sendAsset`** — `{ "sendAsset": { "destination": "0xUSER_C", "amount": "100.0" } }`. Moves collateral from the proxied user's account on the DEX to `destination`'s account on the same venue.

#### Oracle

HIP-3\* venues update prices with the `setOracle` star operation deploy action. `oraclePxs` is a list (sorted by key) of asset and spot oracle prices. External perp prices and mark prices are derived onchain based on the deployer's spot oracle price inputs.

* **External perp prices** are derived from the main dex asset with the same name, with the denomination converted to USDC. For example, `test:BTC` uses the external perp price of `BTC`.
* **Mark prices** are computed onchain as the median of:

  1. the oracle price adjusted by an exponential moving average of the mid price's premium over the oracle price,
  2. the external perp price, and
  3. the local mark price (median(best bid, best ask, last trade price)).

  If only two of these prices are available, an exponential moving average of the local mark price is added as a third input.

#### Permissions

For HIP-3\*, `SubDeployerInput.variant` also accepts the objects shown below.

| Operation                          | Deployer | Sub-deployer grant                                   |
| ---------------------------------- | -------- | ---------------------------------------------------- |
| `modifyApproval`                   | yes      | `{ "hip3Star": "modifyApproval" }`                   |
| `modifyBackstopLiquidatorApproval` | yes      | `{ "hip3Star": "modifyBackstopLiquidatorApproval" }` |
| `setReduceOnly`                    | yes      | `{ "hip3Star": "setReduceOnly" }`                    |
| `cancel`                           | yes      | `{ "hip3Star": "cancel" }`                           |
| `cancelAll`                        | yes      | `{ "hip3Star": "cancelAll" }`                        |
| `order`                            | yes      | `{ "hip3Star": "order" }`                            |
| `sendAsset`                        | yes      | `{ "hip3Star": "sendAsset" }`                        |
| `setOracle`                        | yes      | `{ "hip3Star": "setOracle" }`                        |

Each grant only covers its own operation. For example, the `modifyApproval` grant does not allow `modifyBackstopLiquidatorApproval`, `setReduceOnly`, or `sendAsset`. Likewise, the regular `"setOracle"` grant, including the one given to `oracleUpdater`, does not allow the `setOracle` star operation.

### User star state

The `userStarState` info request returns a user's approval state on every HIP-3\* venue where the user has been approved. The state is `null` on venues that have since removed the user's approval.

```json
{ "type": "userStarState", "user": "0xUSER_A" }
```

```json
{
  "dexToState": {
    "test": {
      "isReduceOnly": false,
      "isBackstopLiquidatorDepositAllowed": true
    },
    "demo": null
  }
}
```
