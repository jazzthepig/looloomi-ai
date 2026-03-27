/**
 * Fund Deploy Wizard — Frontend Component
 *
 * One-click fund deployment UI for Quant GPs.
 * Guides through fund creation, fee configuration, and deployment.
 */

import React, { useState, useCallback } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { Connection, PublicKey } from '@solana/web3.js';

// ============================================================================
// Constants
// ============================================================================

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const USDC_MINT = new PublicKey('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v');

// ============================================================================
// Fee Presets
// ============================================================================

const FEE_PRESETS = {
  conservative: { management: 100, performance: 1000, label: 'Conservative (1%/10%)' },
  standard: { management: 200, performance: 2000, label: 'Standard (2%/20%)' },
  aggressive: { management: 300, performance: 3000, label: 'Aggressive (3%/30%)' },
  custom: { management: 0, performance: 0, label: 'Custom' },
};

// ============================================================================
// Validation
// ============================================================================

function validateFundParams(params) {
  const errors = {};

  if (!params.name || params.name.length < 3) {
    errors.name = 'Fund name must be at least 3 characters';
  }
  if (params.name && params.name.length > 32) {
    errors.name = 'Fund name must be 32 characters or less';
  }

  if (!params.symbol || params.symbol.length < 3) {
    errors.symbol = 'Symbol must be at least 3 characters';
  }
  if (params.symbol && params.symbol.length > 8) {
    errors.symbol = 'Symbol must be 8 characters or less';
  }
  if (params.symbol && !/^[A-Z0-9]+$/.test(params.symbol)) {
    errors.symbol = 'Symbol must be uppercase letters and numbers only';
  }

  if (params.managementFee < 0 || params.managementFee > 10000) {
    errors.managementFee = 'Management fee must be 0-100%';
  }

  if (params.performanceFee < 0 || params.performanceFee > 10000) {
    errors.performanceFee = 'Performance fee must be 0-100%';
  }

  if (params.minInvestment < 1000) {
    errors.minInvestment = 'Minimum investment must be at least $1,000';
  }

  if (params.maxInvestment < params.minInvestment) {
    errors.maxInvestment = 'Maximum must be greater than minimum';
  }

  return errors;
}

// ============================================================================
// Step Components
// ============================================================================

function StepIndicator({ currentStep, totalSteps }) {
  return (
    <div className="flex items-center justify-center mb-8">
      {Array.from({ length: totalSteps }, (_, i) => (
        <React.Fragment key={i}>
          <div
            className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-mono
              ${i < currentStep
                ? 'bg-emerald-500/20 text-emerald-400'
                : i === currentStep
                  ? 'bg-cyan-500/20 text-cyan-400 ring-2 ring-cyan-400/50'
                  : 'bg-white/5 text-white/30'
              }`}
          >
            {i < currentStep ? '✓' : i + 1}
          </div>
          {i < totalSteps - 1 && (
            <div
              className={`w-12 h-0.5 mx-1 ${
                i < currentStep ? 'bg-emerald-500/50' : 'bg-white/10'
              }`}
            />
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

function FeePresetSelector({ selected, onSelect }) {
  return (
    <div className="grid grid-cols-2 gap-3 mb-6">
      {Object.entries(FEE_PRESETS).map(([key, preset]) => (
        <button
          key={key}
          onClick={() => onSelect(key)}
          className={`p-4 rounded-lg border text-left transition-all
            ${selected === key
              ? 'border-cyan-400/50 bg-cyan-400/10'
              : 'border-white/10 bg-white/5 hover:border-white/20'
            }`}
        >
          <div className="text-sm font-mono text-white/80">{preset.label}</div>
        </button>
      ))}
    </div>
  );
}

function FormInput({
  label,
  name,
  type = 'text',
  value,
  onChange,
  error,
  suffix,
  ...props
}) {
  return (
    <div className="mb-4">
      <label className="block text-xs text-white/50 mb-1.5 uppercase tracking-wider">
        {label}
      </label>
      <div className="relative">
        <input
          type={type}
          name={name}
          value={value}
          onChange={onChange}
          className={`w-full bg-black/40 border rounded-lg px-4 py-2.5 text-white font-mono text-sm
            focus:outline-none focus:ring-2 focus:ring-cyan-400/50 transition-all
            ${error ? 'border-red-400/50' : 'border-white/10'}`}
          {...props}
        />
        {suffix && (
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 text-xs">
            {suffix}
          </span>
        )}
      </div>
      {error && <p className="text-red-400 text-xs mt-1">{error}</p>}
    </div>
  );
}

// ============================================================================
// Main Component
// ============================================================================

export default function FundDeployWizard() {
  const { connected, publicKey, signTransaction } = useWallet();
  const [currentStep, setCurrentStep] = useState(0);
  const [feePreset, setFeePreset] = useState('standard');
  const [submitting, setSubmitting] = useState(false);
  const [deployResult, setDeployResult] = useState(null);
  const [errors, setErrors] = useState({});

  const [formData, setFormData] = useState({
    name: '',
    symbol: '',
    managementFee: 200,
    performanceFee: 2000,
    minInvestment: 10000,
    maxInvestment: 1000000,
  });

  // ============================================================================
  // Handlers
  // ============================================================================

  const handleInputChange = useCallback((e) => {
    const { name, value, type } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'number' ? parseInt(value, 10) || 0 : value,
    }));
    // Clear error when user types
    setErrors(prev => ({ ...prev, [name]: undefined }));
  }, []);

  const handleFeePresetChange = useCallback((preset) => {
    setFeePreset(preset);
    if (preset !== 'custom') {
      setFormData(prev => ({
        ...prev,
        managementFee: FEE_PRESETS[preset].management,
        performanceFee: FEE_PRESETS[preset].performance,
      }));
    }
  }, []);

  const handleNext = useCallback(() => {
    if (currentStep === 0) {
      // Validate step 1
      const newErrors = validateFundParams(formData);
      if (Object.keys(newErrors).length > 0) {
        setErrors(newErrors);
        return;
      }
    }
    setCurrentStep(prev => Math.min(prev + 1, 3));
  }, [currentStep, formData]);

  const handleBack = useCallback(() => {
    setCurrentStep(prev => Math.max(prev - 1, 0));
  }, [currentStep]);

  const handleDeploy = useCallback(async () => {
    if (!connected || !publicKey) {
      alert('Please connect your wallet first');
      return;
    }

    setSubmitting(true);
    try {
      // Call backend API to construct transaction
      const response = await fetch(`${API_BASE}/api/v1/factory/deploy`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          fund_id: Math.floor(Date.now() / 1000) % 1000000, // Generate unique ID
          name: formData.name,
          symbol: formData.symbol,
          management_fee_bps: formData.managementFee,
          performance_fee_bps: formData.performanceFee,
          min_investment: formData.minInvestment,
          max_investment: formData.maxInvestment,
          gp_authority: publicKey.toBase58(),
          treasury: publicKey.toBase58(), // In production: separate treasury
        }),
      });

      const result = await response.json();

      if (response.ok) {
        setDeployResult(result);
        setCurrentStep(3); // Move to success step
      } else {
        alert(`Deployment failed: ${result.detail || 'Unknown error'}`);
      }
    } catch (err) {
      alert(`Error: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  }, [connected, publicKey, formData]);

  // ============================================================================
  // Render Steps
  // ============================================================================

  const renderStep0 = () => (
    <div>
      <h3 className="text-lg font-medium text-white mb-6">Fund Configuration</h3>

      <FormInput
        label="Fund Name"
        name="name"
        value={formData.name}
        onChange={handleInputChange}
        error={errors.name}
        placeholder="EST Alpha Growth Fund"
        maxLength={32}
      />

      <FormInput
        label="Symbol"
        name="symbol"
        value={formData.symbol}
        onChange={handleInputChange}
        error={errors.symbol}
        placeholder="ESTAGF"
        maxLength={8}
      />

      <div className="mt-6 text-xs text-white/40">
        <p>Fund will be deployed on Solana Devnet for testing.</p>
        <p>Mainnet deployment requires additional security audit.</p>
      </div>
    </div>
  );

  const renderStep1 = () => (
    <div>
      <h3 className="text-lg font-medium text-white mb-6">Fee Structure</h3>

      <FeePresetSelector selected={feePreset} onSelect={handleFeePresetChange} />

      <div className="grid grid-cols-2 gap-4">
        <FormInput
          label="Management Fee"
          name="managementFee"
          type="number"
          value={formData.managementFee}
          onChange={handleInputChange}
          error={errors.managementFee}
          suffix="bps"
        />
        <FormInput
          label="Performance Fee"
          name="performanceFee"
          type="number"
          value={formData.performanceFee}
          onChange={handleInputChange}
          error={errors.performanceFee}
          suffix="bps"
        />
      </div>

      <div className="mt-4 p-4 bg-white/5 rounded-lg">
        <div className="text-xs text-white/50 mb-2">Fee Explanation</div>
        <div className="text-sm text-white/80">
          <p>Management Fee: Annual fee charged on AUM ({formData.managementFee / 100}%)</p>
          <p>Performance Fee: Share of profits above high water mark ({formData.performanceFee / 100}%)</p>
        </div>
      </div>
    </div>
  );

  const renderStep2 = () => (
    <div>
      <h3 className="text-lg font-medium text-white mb-6">Investment Limits</h3>

      <FormInput
        label="Minimum Investment"
        name="minInvestment"
        type="number"
        value={formData.minInvestment}
        onChange={handleInputChange}
        error={errors.minInvestment}
        suffix="USDC"
      />

      <FormInput
        label="Maximum Investment"
        name="maxInvestment"
        type="number"
        value={formData.maxInvestment}
        onChange={handleInputChange}
        error={errors.maxInvestment}
        suffix="USDC"
      />

      <div className="mt-6 p-4 bg-amber-400/10 border border-amber-400/20 rounded-lg">
        <div className="text-xs text-amber-400/80 mb-1">⚠️ Review before deployment</div>
        <div className="text-sm text-white/80">
          <p>Fund Name: {formData.name} ({formData.symbol})</p>
          <p>Fees: {formData.managementFee / 100}% management, {formData.performanceFee / 100}% performance</p>
          <p>Investment range: ${formData.minInvestment.toLocaleString()} - ${formData.maxInvestment.toLocaleString()}</p>
        </div>
      </div>
    </div>
  );

  const renderStep3 = () => (
    <div className="text-center">
      {deployResult ? (
        <>
          <div className="w-16 h-16 bg-emerald-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
            <span className="text-3xl">✓</span>
          </div>
          <h3 className="text-xl font-medium text-white mb-4">Fund Deployed Successfully!</h3>
          <div className="bg-white/5 rounded-lg p-4 text-left">
            <div className="text-xs text-white/50 mb-2">Transaction Details</div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-white/60">Fund ID:</span>
                <span className="text-white font-mono">{deployResult.fund_id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-white/60">Status:</span>
                <span className="text-emerald-400">{deployResult.status}</span>
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="animate-pulse">
          <div className="w-16 h-16 bg-cyan-500/20 rounded-full flex items-center justify-center mx-auto mb-6">
            <span className="text-3xl">⟳</span>
          </div>
          <h3 className="text-lg font-medium text-white">Deploying Fund...</h3>
          <p className="text-white/50 text-sm mt-2">Please sign the transaction in your wallet</p>
        </div>
      )}
    </div>
  );

  // ============================================================================
  // Render
  // ============================================================================

  return (
    <div className="max-w-lg mx-auto">
      <div className="bg-gradient-to-b from-white/5 to-transparent border border-white/10 rounded-2xl p-6">
        {/* Header */}
        <div className="text-center mb-8">
          <h2 className="text-xl font-semibold text-white mb-2">Deploy Tokenized Fund</h2>
          <p className="text-sm text-white/50">One-click deployment on Solana</p>
        </div>

        {/* Step Indicator */}
        <StepIndicator currentStep={currentStep} totalSteps={4} />

        {/* Step Content */}
        <div className="min-h-[320px]">
          {currentStep === 0 && renderStep0()}
          {currentStep === 1 && renderStep1()}
          {currentStep === 2 && renderStep2()}
          {currentStep === 3 && renderStep3()}
        </div>

        {/* Navigation */}
        {currentStep < 3 && (
          <div className="flex gap-3 mt-8">
            {currentStep > 0 && (
              <button
                onClick={handleBack}
                className="flex-1 py-3 rounded-lg border border-white/10 text-white/70
                  hover:bg-white/5 transition-all"
              >
                Back
              </button>
            )}
            <button
              onClick={currentStep === 2 ? handleDeploy : handleNext}
              disabled={submitting || !connected}
              className={`flex-1 py-3 rounded-lg font-medium transition-all
                ${!connected
                  ? 'bg-white/10 text-white/30 cursor-not-allowed'
                  : 'bg-gradient-to-r from-cyan-500 to-blue-500 text-white hover:opacity-90'
                }`}
            >
              {!connected
                ? 'Connect Wallet'
                : currentStep === 2
                  ? (submitting ? 'Deploying...' : 'Deploy Fund')
                  : 'Continue'
              }
            </button>
          </div>
        )}

        {/* Success Actions */}
        {currentStep === 3 && deployResult && (
          <div className="flex gap-3 mt-8">
            <button
              onClick={() => window.location.reload()}
              className="flex-1 py-3 rounded-lg border border-white/10 text-white/70
                hover:bg-white/5 transition-all"
            >
              Deploy Another
            </button>
            <button
              onClick={() => {/* Navigate to fund dashboard */}}
              className="flex-1 py-3 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-500
                text-white hover:opacity-90 transition-all"
            >
              View Fund
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
