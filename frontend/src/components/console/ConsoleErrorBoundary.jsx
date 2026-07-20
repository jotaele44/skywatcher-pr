import React from 'react';
import { RuntimeUnavailable } from './RuntimeUnavailable';

export class ConsoleErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.props.onError?.(error, info);
  }

  render() {
    if (this.state.error) {
      return <RuntimeUnavailable reason={this.state.error.message || 'The console runtime failed.'} />;
    }
    return this.props.children;
  }
}
