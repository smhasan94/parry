import { useState, useCallback } from "react";
import { useNavigate } from "@tanstack/react-router";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useCreateApiKey } from "@/hooks/useApiKeys";
import { useBlockingSettings, useUpdateBlockingSettings } from "@/hooks/useBlockingSettings";
import { Key, Copy, Check, ArrowRight, Terminal, Rocket, Shield } from "lucide-react";

const STEPS = [
  { label: "Create API Key", icon: Key },
  { label: "Install SDK", icon: Terminal },
  { label: "Enable Blocking", icon: Shield },
  { label: "All Set", icon: Rocket },
] as const;

const CODE_SNIPPET = `import parry
parry.init(api_key="<paste-your-key>")

from parry import ParryOpenAI
client = ParryOpenAI(agent_id="my-first-agent")

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)`;

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [text]);

  return (
    <Button variant="ghost" size="icon" onClick={handleCopy} aria-label="Copy to clipboard">
      {copied ? <Check className="h-4 w-4 text-green-400" /> : <Copy className="h-4 w-4" />}
    </Button>
  );
}

function StepIndicator({ currentStep }: { currentStep: number }) {
  return (
    <div className="flex items-center justify-center gap-2">
      {STEPS.map((step, i) => {
        const Icon = step.icon;
        const isActive = i === currentStep;
        const isComplete = i < currentStep;
        return (
          <div key={step.label} className="flex items-center gap-2">
            {i > 0 && (
              <div
                className={`h-px w-8 sm:w-12 ${isComplete ? "bg-primary" : "bg-border"}`}
              />
            )}
            <div
              className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-primary text-primary-foreground"
                  : isComplete
                    ? "bg-primary/20 text-primary"
                    : "bg-secondary text-muted-foreground"
              }`}
            >
              <Icon className="h-4 w-4" />
              <span className="hidden sm:inline">{step.label}</span>
              <span className="sm:hidden">{i + 1}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StepCreateKey({
  onNext,
}: {
  onNext: () => void;
}) {
  const [keyName, setKeyName] = useState("My First Key");
  const [rawKey, setRawKey] = useState<string | null>(null);
  const createApiKey = useCreateApiKey();

  const handleCreate = () => {
    createApiKey.mutate(keyName, {
      onSuccess: (data) => {
        setRawKey(data.raw_key);
      },
    });
  };

  return (
    <Card className="mx-auto w-full max-w-lg">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Key className="h-5 w-5" />
          Create your first API key
        </CardTitle>
        <CardDescription>
          API keys authenticate your agents with Parry. Give it a name so you can identify it later.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!rawKey ? (
          <div className="space-y-4">
            <div className="space-y-2">
              <label htmlFor="key-name" className="text-sm font-medium text-foreground">
                Key name
              </label>
              <Input
                id="key-name"
                value={keyName}
                onChange={(e) => setKeyName(e.target.value)}
                placeholder="e.g. My First Key"
              />
            </div>
            <Button
              onClick={handleCreate}
              disabled={createApiKey.isPending || !keyName.trim()}
              className="w-full"
            >
              {createApiKey.isPending ? "Creating..." : "Create Key"}
            </Button>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="rounded-md border border-border bg-secondary p-3">
              <div className="flex items-center justify-between gap-2">
                <code className="flex-1 break-all text-sm text-foreground">{rawKey}</code>
                <CopyButton text={rawKey} />
              </div>
            </div>
            <div className="rounded-md border border-yellow-500/30 bg-yellow-500/10 p-3">
              <p className="text-sm text-yellow-400">
                Save this key — it won't be shown again.
              </p>
            </div>
            <Button onClick={onNext} className="w-full">
              Next
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function StepInstallSDK({ onNext }: { onNext: () => void }) {
  const pipCommand = "pip install parry";

  return (
    <Card className="mx-auto w-full max-w-lg">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Terminal className="h-5 w-5" />
          Install the SDK
        </CardTitle>
        <CardDescription>
          Add Parry to your project and wrap your LLM client. It takes two minutes.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <p className="text-sm font-medium text-foreground">Install via pip</p>
          <div className="flex items-center justify-between rounded-md border border-border bg-secondary p-3">
            <code className="text-sm text-foreground">{pipCommand}</code>
            <CopyButton text={pipCommand} />
          </div>
        </div>

        <div className="space-y-2">
          <p className="text-sm font-medium text-foreground">Initialize and send your first event</p>
          <div className="relative rounded-md border border-border bg-secondary p-3">
            <div className="absolute right-2 top-2">
              <CopyButton text={CODE_SNIPPET} />
            </div>
            <pre className="overflow-x-auto pr-10 text-sm text-foreground">
              <code>{CODE_SNIPPET}</code>
            </pre>
          </div>
        </div>

        <Button onClick={onNext} className="w-full">
          Next
          <ArrowRight className="ml-2 h-4 w-4" />
        </Button>
      </CardContent>
    </Card>
  );
}

function StepEnableBlocking({ onNext }: { onNext: () => void }) {
  const { data, isLoading } = useBlockingSettings();
  const updateBlocking = useUpdateBlockingSettings();
  const alreadyEnabled = data?.blocking_enabled ?? false;

  const handleEnable = () => {
    if (alreadyEnabled) {
      onNext();
      return;
    }
    updateBlocking.mutate(true, { onSuccess: () => onNext() });
  };

  return (
    <Card className="mx-auto w-full max-w-lg">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Shield className="h-5 w-5" />
          Block attacks in real time?
        </CardTitle>
        <CardDescription>
          With blocking enabled, Parry rejects prompt injections, tool misuse,
          and policy violations <em>before</em> they hit your LLM. Observe-only
          just logs them. You can change this anytime in Settings.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {alreadyEnabled && (
          <div className="rounded-md border border-green-500/30 bg-green-500/10 p-3 text-sm text-green-400">
            Blocking mode is already enabled for this org.
          </div>
        )}
        <div className="space-y-2">
          <Button
            onClick={handleEnable}
            disabled={isLoading || updateBlocking.isPending}
            className="w-full"
          >
            {updateBlocking.isPending
              ? "Enabling..."
              : alreadyEnabled
                ? "Continue"
                : "Enable blocking — recommended"}
            <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
          {!alreadyEnabled && (
            <Button
              variant="ghost"
              onClick={onNext}
              disabled={updateBlocking.isPending}
              className="w-full"
            >
              Skip — log only
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function StepComplete() {
  const navigate = useNavigate();

  return (
    <Card className="mx-auto w-full max-w-lg">
      <CardHeader className="text-center">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-green-500/10">
          <Rocket className="h-8 w-8 text-green-400" />
        </div>
        <CardTitle>You're all set!</CardTitle>
        <CardDescription>
          Your API key is created and you're ready to start monitoring your AI agents. Events will
          appear on the dashboard as your agents make LLM calls.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button onClick={() => navigate({ to: "/dashboard" })} className="w-full">
          Go to Dashboard
          <ArrowRight className="ml-2 h-4 w-4" />
        </Button>
      </CardContent>
    </Card>
  );
}

export function OnboardingPage() {
  const [currentStep, setCurrentStep] = useState(0);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background">
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <h1 className="text-lg font-semibold text-foreground">Parry Setup</h1>
        <StepIndicator currentStep={currentStep} />
        <div className="w-24" />
      </div>

      <div className="flex flex-1 items-center justify-center p-6">
        {currentStep === 0 && <StepCreateKey onNext={() => setCurrentStep(1)} />}
        {currentStep === 1 && <StepInstallSDK onNext={() => setCurrentStep(2)} />}
        {currentStep === 2 && <StepEnableBlocking onNext={() => setCurrentStep(3)} />}
        {currentStep === 3 && <StepComplete />}
      </div>
    </div>
  );
}
